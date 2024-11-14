#!/bin/bash

# Wait until primary database is ready
until pg_isready -h postgres-primary -p 5432 -U postgres; do
  echo "Waiting for primary database to be ready..."
  sleep 2
done

# Stop the PostgreSQL server
pg_ctlcluster 13 main stop

# Copy the data from the primary
pg_basebackup -h postgres-primary -D /var/lib/postgresql/data -U postgres -Fp -Xs -P -R

# Start PostgreSQL server
pg_ctlcluster 13 main start

# Keep container running
tail -f /dev/null
