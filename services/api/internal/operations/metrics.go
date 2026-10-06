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
		var paused int64
		e := db.QueryRow(ctx, `SELECT count(*) FROM operations_controls CROSS JOIN LATERAL jsonb_each(paused) item WHERE item.value='true'::jsonb`).Scan(&paused)
		if e != nil {
			fmt.Fprintln(w, "nautiq_operations_database_available 0")
			return
		}
		fmt.Fprintf(w, "nautiq_operations_database_available 1\nnautiq_incident_scopes_paused %d\n", paused)
	}
}
