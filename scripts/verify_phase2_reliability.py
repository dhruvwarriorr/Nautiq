"""Crash/replay/revision verification in a disposable database and object prefix."""

import base64
import subprocess
import tempfile
from pathlib import Path

from verify_argo_parser import fixture

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.nc"
        fixture(path, "R")
        raw = base64.b64encode(path.read_bytes()).decode()
        fixture(path, "D", bad_salinity=True)
        delayed = base64.b64encode(path.read_bytes()).decode()
    migrations = [p.read_text() for p in sorted((ROOT / "migrations").glob("*.sql"))]
    code = r"""
import base64,io,json,os,uuid,hashlib
from datetime import datetime,timezone
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from urllib.parse import urlsplit,urlunsplit
from nautiuq_ml.argo.worker import process,store,repair,repair_lake,read_object,decode_envelope,InvalidProfile
name="argo_verify_"+uuid.uuid4().hex[:12]
original=os.environ["DATABASE_URL"]
s3=store()
prefix="verification/"+name+"/"
admin=psycopg.connect(original,autocommit=True)
admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
parts=urlsplit(original)
os.environ["DATABASE_URL"]=urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))
try:
 with psycopg.connect(os.environ["DATABASE_URL"],autocommit=True) as db:
  for migration in MIGRATIONS:db.execute(migration)
 run=str(uuid.uuid4())
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:db.execute("INSERT INTO ingestion_runs(run_id,source_id) VALUES(%s,'argo_gdac')",(run,))
 def register(data,ordinal):
  sha=hashlib.sha256(data).hexdigest();artifact=str(uuid.uuid4());event=str(uuid.uuid4());key=prefix+str(ordinal)+".nc"
  s3.put_object("nautiuq",key,io.BytesIO(data),len(data))
  with psycopg.connect(os.environ["DATABASE_URL"]) as db:
   db.execute("INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id) VALUES(%s,'argo_gdac',%s,%s,now(),%s,%s,%s,'profile',%s)",(artifact,"aoml/2902768/profiles/R2902768_001.nc","https://data-argo.ifremer.fr/dac/aoml/2902768/profiles/R2902768_001.nc",sha,key,len(data),run))
  return json.dumps({"event_id":event,"event_type":"raw.received","schema_version":1,"aggregate_key":artifact,"revision_sha256":sha,"payload":{"artifact_id":artifact},"created_at":datetime.now(timezone.utc).isoformat()}).encode()
 def counts():
  with psycopg.connect(os.environ["DATABASE_URL"]) as db:return db.execute("SELECT (SELECT count(*) FROM profiles),(SELECT count(*) FROM profile_revisions),(SELECT count(*) FROM consumer_inbox)").fetchone()
 event=register(base64.b64decode(RAW),1)
 for replacement in [{"event_id":1},{"schema_version":True},{"payload":[]},{"created_at":"2026-10-01T00:00:00"}]:
  malformed=dict(json.loads(event),**replacement)
  try:decode_envelope(json.dumps(malformed).encode())
  except InvalidProfile:pass
  else:raise AssertionError("Invalid typed event envelope accepted")
 assert process(event)=="normalized"
 initial=counts();assert initial[:2]==(2,2),initial
 assert process(event)=="duplicate" and counts()==initial
 # New event ID with identical raw artifact simulates lost broker/consumer acknowledgement.
 redelivery=json.loads(event);redelivery["event_id"]=str(uuid.uuid4())
 assert process(json.dumps(redelivery).encode())=="normalized"
 assert counts()[:2]==initial[:2]
 d=register(base64.b64decode(DELAYED),2)
 assert process(d)=="normalized"
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  modes=db.execute("SELECT data_mode,count(*) FROM profile_revisions WHERE superseded_at IS NULL AND selected_at IS NOT NULL GROUP BY data_mode").fetchall()
  assert modes==[("D",2)],modes
  assert db.execute("SELECT count(*) FROM profile_revisions WHERE superseded_at IS NOT NULL").fetchone()[0]==2
 # Older real-time data arriving late cannot replace adjusted D revisions.
 late=json.loads(event);late["event_id"]=str(uuid.uuid4());process(json.dumps(late).encode())
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  assert db.execute("SELECT count(*) FROM profile_revisions WHERE data_mode='D' AND selected_at IS NOT NULL AND superseded_at IS NULL").fetchone()[0]==2
 # A DB failure after lake staging leaves no inbox/canonical partial commit.
 failing=dict(json.loads(d),event_id=str(uuid.uuid4()))
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:db.execute("ALTER TABLE consumer_inbox ADD CONSTRAINT forced_failure CHECK (consumer_name <> 'argo-normalizer-v1') NOT VALID")
 before=counts()
 try:process(json.dumps(failing).encode())
 except psycopg.errors.CheckViolation:pass
 else:raise AssertionError("Failure did not roll back")
 assert counts()==before
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:db.execute("ALTER TABLE consumer_inbox DROP CONSTRAINT forced_failure")
 assert process(json.dumps(failing).encode())=="normalized"
 poison=register(b"not a NetCDF file",3)
 assert process(poison)=="quarantined"
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  assert db.execute("SELECT count(*) FROM ingestion_quarantine").fetchone()[0]>=1
  for key,sha in db.execute("SELECT parquet_key,parquet_sha256 FROM profile_revisions").fetchall():assert hashlib.sha256(read_object(s3,key,sha)).hexdigest()==sha
 # Missing lake files are reproducibly reconstructed; corrupt immutable files are withheld.
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  revision,key,sha=db.execute("SELECT revision_sha256,parquet_key,parquet_sha256 FROM profile_revisions ORDER BY revision_id LIMIT 1").fetchone()
 s3.remove_object("nautiuq","lake/manifests/"+revision+".json")
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:repair_lake(db,s3)
 s3.stat_object("nautiuq","lake/manifests/"+revision+".json")
 s3.remove_object("nautiuq",key)
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:repair_lake(db,s3)
 read_object(s3,key,sha)
 s3.put_object("nautiuq",key,io.BytesIO(b"corrupt"),7,metadata={"sha256":sha})
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  repair_lake(db,s3)
  assert db.execute("SELECT science_ready FROM profile_revisions WHERE revision_sha256=%s",(revision,)).fetchone()[0] is False
 assert s3.stat_object("nautiuq",key).size==7,"Corruption was silently overwritten"
 s3.remove_object("nautiuq",key)
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  repair_lake(db,s3)
  assert db.execute("SELECT science_ready FROM profile_revisions WHERE revision_sha256=%s",(revision,)).fetchone()[0] is True
 # Raw persisted before SQL/outbox registration is recovered using immutable source metadata.
 orphan=base64.b64decode(RAW);osha=hashlib.sha256(orphan).hexdigest()
 source_path="aoml/2902768/profiles/R2902768_099.nc"
 oid=str(uuid.uuid5(uuid.NAMESPACE_URL,"argo_gdac|"+source_path+"|"+osha))
 s3.put_object("nautiuq",prefix+"orphan.nc",io.BytesIO(orphan),len(orphan),metadata={"sha256":osha,"source_path":source_path,"source_updated_at":"2026-09-30T00:00:00Z"})
 repair(raw_prefix=prefix)
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  assert db.execute("SELECT count(*) FROM raw_artifacts WHERE artifact_id=%s",(oid,)).fetchone()[0]==1
  eid=db.execute("SELECT event_id FROM event_outbox WHERE aggregate_key=%s",(oid,)).fetchone()[0]
  db.execute("UPDATE event_outbox SET published_at=now()-interval '10 minutes' WHERE event_id=%s",(eid,))
 repair(raw_prefix=prefix)
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:assert db.execute("SELECT published_at FROM event_outbox WHERE event_id=%s",(eid,)).fetchone()[0] is None
 print("Disposable DB passed: immutable revisions, R→D supersession, late R, duplicate delivery, commit/ack replay, atomic rollback after lake staging, poison quarantine, Parquet integrity, missing lake reconstruction, corrupt lake withholding, orphan raw/outbox recovery, broker retention replay")
finally:
 # Remove only the objects produced by this isolated verification database.
 with psycopg.connect(os.environ["DATABASE_URL"]) as db:
  for key, in db.execute("SELECT manifest_key FROM calculations").fetchall():
   s3.remove_object("nautiuq",key)
  for revision,key in db.execute("SELECT revision_sha256,parquet_key FROM profile_revisions").fetchall():
   s3.remove_object("nautiuq",key);s3.remove_object("nautiuq","lake/manifests/"+revision+".json")
 for obj in s3.list_objects("nautiuq",prefix=prefix,recursive=True):s3.remove_object("nautiuq",obj.object_name)
 admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
 admin.close()
"""
    payload = f"MIGRATIONS={migrations!r}\nRAW={raw!r}\nDELAYED={delayed!r}\n" + code
    subprocess.run(
        ["docker", "compose", "exec", "-T", "normalizer", "python", "-"],
        input=payload,
        text=True,
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
