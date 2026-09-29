---
name: sql-queries
description: Guidance for writing, reviewing, and optimizing SQL queries
keywords: [sql, query, select, join, database, postgres, postgresql, mysql, sqlite, index, indexes, schema, table]
---

When writing or reviewing SQL:

1. Ask (or state an assumption explicitly) which database engine is in use if it affects syntax (PostgreSQL vs. MySQL vs. SQLite window functions, `LIMIT`/`TOP`, upsert syntax, etc. all differ).
2. Prefer explicit column lists over `SELECT *` in any query meant to be reused or put in application code -- schema changes silently break `SELECT *` consumers.
3. When a query joins multiple tables, state which join type (INNER/LEFT/etc.) is correct for the question being asked, and why -- a wrong join type is one of the most common silent-bug sources in SQL.
4. If the user describes slow performance, ask about table size and existing indexes before proposing a rewrite; suggest `EXPLAIN`/`EXPLAIN ANALYZE` output as the next diagnostic step rather than guessing at the bottleneck.
5. Flag N+1 query patterns (a query run in a loop per row of an outer result) when you see them in application code, and suggest a single join or batched query instead.
6. For any query that writes data (`UPDATE`/`DELETE`), point out the blast radius if the `WHERE` clause is missing or too broad, before the user runs it.
