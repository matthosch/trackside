-- Which parser version produced each file's staged rows (timing.PARSER_VERSION).
-- The load step reprocesses any file stamped with an older version, so a parser
-- fix backfills itself on the next run with no hand-written data migration.
-- Existing rows start as NULL, so everything already loaded is reprocessed once.
ALTER TABLE raw.timing_files ADD COLUMN parser_version integer;
