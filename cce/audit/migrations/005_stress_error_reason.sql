-- Records WHY a stress scenario produced no verdict.
--
-- 004 added `status`, so an ERROR is now distinguishable from a FAILED run.
-- But an unexplained ERROR tells a risk manager that something went wrong and
-- nothing about what -- and the log line carrying the reason is not in front
-- of them when they are reading the decision record.
--
-- The reason matters most for the failure this column was added alongside: a
-- scenario whose shock keys match no asset or sector applies nothing, and
-- used to report a clean PASS. "shock keys match no asset or sector: BANKING_"
-- is the difference between finding that typo and not.

ALTER TABLE stress_results
    ADD COLUMN error_reason TEXT;
