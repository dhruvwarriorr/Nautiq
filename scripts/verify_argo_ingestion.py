"""Offline GDAC discovery/transport contracts, with a temporary Go check file."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = r"""
package main
import (
 "bytes"
 "compress/gzip"
 "context"
 "io"
 "net/http"
 "strings"
 "testing"
 "time"
)
type checkTransport func(*http.Request)(*http.Response,error)
func (f checkTransport) RoundTrip(r *http.Request)(*http.Response,error){return f(r)}
func zipIndex(s string) []byte {var b bytes.Buffer;g:=gzip.NewWriter(&b);g.Write([]byte(s));g.Close();return b.Bytes()}
func TestPhase2Discovery(t *testing.T){
 a:=App{cfg:Config{MaxCandidates:2,MaxExpanded:4096,MaxLine:4096},observedSince:time.Date(2025,10,1,0,0,0,0,time.UTC)}
 a.cfg.Domain.West=45;a.cfg.Domain.East=100;a.cfg.Domain.South=0;a.cfg.Domain.North=30
 header:="file,date,latitude,longitude,ocean,profiler_type,institution,date_update\n"
 row:=func(path,lat,update string) string{return path+",20261001000000,"+lat+",70,I,846,AO,"+update+"\n"}
 body:=header+row("aoml/2902768/profiles/R2902768_003.nc","10","20261001000300")+row("aoml/2902768/profiles/R2902768_002.nc","10","20261001000200")+row("aoml/2902768/profiles/R2902768_001.nc","10","20261001000200")+row("aoml/2902768/profiles/R2902768_004.nc","40","20261001000100")+row("../../evil.nc","10","20261001000100")+row("aoml/2902768/profiles/R2902768_005.nc","NaN","20261001000100")
 got,bad,err:=a.discover(zipIndex(body),map[string]bool{},time.Time{})
 if err!=nil||bad!=2||len(got)!=2||!strings.HasSuffix(got[0].Path,"_001.nc")||!strings.HasSuffix(got[1].Path,"_002.nc"){t.Fatalf("Bounded ordering/filter/path validation: %v %d %v",got,bad,err)}
 known:=map[string]bool{key(got[0].Path,got[0].Updated):true}
 again,_,err:=a.discover(zipIndex(body),known,time.Time{})
 if err!=nil||len(again)!=2||again[0].Path==got[0].Path{t.Fatal("Persisted discovery did not skip delivered tie")}
 empty,_,err:=a.discover(zipIndex(body),known,time.Date(2026,10,2,0,0,0,0,time.UTC))
 if err!=nil||len(empty)!=0{t.Fatal("Update cutoff not respected")}
 if _,_,err=a.discover([]byte("corrupt gzip"),nil,time.Time{});err==nil{t.Fatal("Corrupt index accepted")}
 a.cfg.MaxExpanded=20
 if _,_,err=a.discover(zipIndex(body),nil,time.Time{});err==nil{t.Fatal("Expanded index budget ignored")}
 a.cfg.MaxExpanded=4096;a.cfg.MaxLine=32
 if _,_,err=a.discover(zipIndex(body),nil,time.Time{});err==nil{t.Fatal("Line budget ignored")}
}
func TestPhase2Transport(t *testing.T){
 for _,tc:=range []struct{status int;size int64;retry,body,reason string}{
 {404,0,"","","provider_http_404"},{410,0,"","","provider_http_410"},
 {429,0,"31","","provider_retry_window"},{200,20,"","oversize","object_too_large"},
 {200,3,"","abc",""},{304,0,"","",""},
 }{
  gate:=make(chan time.Time,3);for i:=0;i<3;i++{gate<-time.Now()}
  calls:=0
  a:=App{cfg:Config{MaxBytes:10,Deadline:1},gate:gate,http:&http.Client{Transport:checkTransport(func(r *http.Request)(*http.Response,error){
   calls++;if r.Header.Get("Accept-Encoding")!="identity"{t.Fatal("Unbounded content encoding")}
   h:=make(http.Header);h.Set("Retry-After",tc.retry)
   return &http.Response{StatusCode:tc.status,Header:h,ContentLength:tc.size,Body:io.NopCloser(strings.NewReader(tc.body))},nil
  })}}
  data,_,status,err:=a.fetch(context.Background(),"https://data-argo.ifremer.fr/dac/aoml/2902768/profiles/R2902768_001.nc",nil)
  if tc.reason!=""{if err==nil||err.Error()!=tc.reason{t.Fatalf("Wrong bounded failure: %v",err)}}else if err!=nil||status!=tc.status||string(data)!=tc.body{t.Fatalf("Transport success changed: %d %v",status,err)}
  if calls!=1{t.Fatal("Permanent failure caused retries")}
  if _,_,_,err=a.fetch(context.Background(),"http://127.0.0.1/private",nil);err==nil||calls!=1{t.Fatal("Unsafe destination reached transport")}
 }
}
"""


def main():
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="phase2_check_",
        suffix="_test.go",
        dir=ROOT / "services/ingestion/cmd/ingestion",
        delete=False,
    ) as file:
        file.write(CHECK)
        path = Path(file.name)
    try:
        subprocess.run(
            ["go", "test", "-race", "-run", "TestPhase2", "./..."],
            cwd=ROOT / "services/ingestion",
            check=True,
        )
    finally:
        path.unlink(missing_ok=True)
    print(
        "Offline GDAC checks passed: bounded cursor ties/order, persisted discovery, domain/time filters, traversal/nonfinite refusal, compressed/line budgets, provider errors/retry limits, transfer bounds, unsafe destination denial"
    )


if __name__ == "__main__":
    main()
