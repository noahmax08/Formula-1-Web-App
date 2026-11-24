#!/bin/bash
# F1 Race Results Tracker -- recreates the database and runs all SQL files.
# DBMS: SQLite 3 (needs the sqlite3 command-line shell).
# Usage: bash run_queries.sh   (run from the folder containing the .sql files)

DB="f1.db"

echo "Recreating database..."
rm -f "$DB"

sqlite3 -bail "$DB" < schema.sql || { echo "schema.sql failed."; exit 1; }
sqlite3 -bail "$DB" < insert_data.sql || { echo "insert_data.sql failed."; exit 1; }

echo
echo "Running queries..."
sqlite3 -header -column "$DB" < queries.sql

echo
echo "Running transaction..."
sqlite3 -header -column -bail "$DB" < transaction.sql
status=$?

if [ "$status" -eq 0 ]; then
    echo
    echo "Transaction completed successfully (rolled back for the demo)."
else
    echo
    echo "Transaction failed."
    echo "Uncommitted changes were rolled back."
fi

echo
echo "Done."
