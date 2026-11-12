# PostgreSQL notes

## Vacuum

Vacuum reclaims space from dead tuples left behind by updates and deletes. Autovacuum runs it in the background.

## Indexes

A GIN index speeds up full-text search over tsvector columns. The HNSW index in pgvector accelerates nearest neighbour search over embeddings.
