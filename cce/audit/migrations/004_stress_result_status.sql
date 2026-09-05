-- Records the full StressStatus, not just a pass/fail bit.
--
-- StressStatus distinguishes PASSED, FAILED, NOT_RUN and ERROR. Collapsing
-- all four into `passed` keeps INV-10 intact -- nothing but PASSED ever reads
-- as safe -- but it loses the difference between "the scenario ran and the
-- portfolio failed it" and "the stress engine errored and we know nothing".
-- Those call for different responses, and the audit trail is where someone
-- looks to tell them apart after the fact.
--
-- NOT_RUN is the default because a row written before this column existed
-- cannot be assumed to have run cleanly. Absence of evidence is not evidence
-- of safety.

ALTER TABLE stress_results
    ADD COLUMN status TEXT NOT NULL DEFAULT 'NOT_RUN'
    CHECK (status IN ('PASSED', 'FAILED', 'NOT_RUN', 'ERROR'));
