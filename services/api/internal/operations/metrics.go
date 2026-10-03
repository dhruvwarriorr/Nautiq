package operations

import (
	"context"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"time"
)

func (m *Monitor) OperationalMetrics(db *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		m.Metrics(w, r)
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		var queued, failed, paused int64
		var workerAge float64
		e := db.QueryRow(ctx, `SELECT (SELECT count(*) FROM notification_deliveries WHERE state IN ('pending','sending')),(SELECT count(*) FROM notification_deliveries WHERE state='failed'),(SELECT count(*) FROM operations_controls CROSS JOIN LATERAL jsonb_each(paused) item WHERE item.value='true'::jsonb),COALESCE((SELECT extract(epoch FROM now()-max(success_at)) FROM notification_worker_health),-1)`).Scan(&queued, &failed, &paused, &workerAge)
		if e != nil {
			fmt.Fprintln(w, "nautiq_operations_database_available 0")
			return
		}
		fmt.Fprintf(w, "nautiq_operations_database_available 1\nnautiq_notification_queue_pending %d\nnautiq_notification_queue_failed %d\nnautiq_incident_scopes_paused %d\nnautiq_notification_worker_success_age_seconds %f\n", queued, failed, paused, workerAge)
	}
}
