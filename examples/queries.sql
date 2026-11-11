-- name: steady_rms_vs_vr
SELECT s.record_id, ROUND(a.value_num, 3) AS vr,
       ROUND(s.rms, 5) AS steady_rms_m
FROM segments s
JOIN attrs a ON a.record_id = s.record_id AND a.key = 'vr'
WHERE s.tag = 'steady'
  AND NOT EXISTS (
      SELECT 1 FROM checks c
      WHERE c.record_id = s.record_id AND c.status = 'fail'
  )
ORDER BY a.value_num, s.record_id, s.channel, s.segment_id;

-- name: check_failure_rates
-- All check results, including not_testable, enter the denominator.
-- Exponent notation keeps division in floating point on both databases.
SELECT check_name,
       SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) AS failure_count,
       1e0 * SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) / COUNT(*) AS failure_rate
FROM checks
GROUP BY check_name
ORDER BY check_name;

-- name: longest_steady_segment
WITH ordered_segments AS (
    SELECT record_id, channel, start_s, end_s,
           ROW_NUMBER() OVER (
               PARTITION BY record_id
               ORDER BY end_s - start_s DESC, segment_id
           ) AS segment_order
    FROM segments
    WHERE tag = 'steady'
)
SELECT record_id, channel, start_s, end_s, end_s - start_s AS duration_s
FROM ordered_segments
WHERE segment_order = 1
ORDER BY record_id;

-- name: clean_rms_rank
SELECT s.record_id, s.channel, s.rms,
       RANK() OVER (PARTITION BY s.channel ORDER BY s.rms DESC) AS rms_rank
FROM segments s
WHERE s.tag = 'steady'
  AND NOT EXISTS (
      SELECT 1 FROM checks c
      WHERE c.record_id = s.record_id AND c.status = 'fail'
  )
ORDER BY s.channel, rms_rank, s.record_id, s.segment_id;

-- name: steady_coverage
-- Tags include the final sample interval; add that interval when the rate is known.
WITH record_time AS (
    SELECT record_id, duration_s + COALESCE(1e0 / sample_rate_hz, 0) AS span_s
    FROM records
), steady_time AS (
    SELECT record_id, channel, SUM(end_s - start_s) AS steady_s
    FROM segments
    WHERE tag = 'steady'
    GROUP BY record_id, channel
)
SELECT r.record_id, t.channel, t.steady_s, t.steady_s / r.span_s AS steady_share
FROM record_time r
JOIN steady_time t ON t.record_id = r.record_id
WHERE r.span_s > 0 AND t.steady_s >= 0.5 * r.span_s
ORDER BY r.record_id, t.channel;

-- name: segment_tag_shares
-- Shares use the total tagged time for each channel, across all records.
WITH tag_time AS (
    SELECT channel, tag, SUM(end_s - start_s) AS total_s
    FROM segments
    GROUP BY channel, tag
)
SELECT channel, tag, total_s,
       total_s / SUM(total_s) OVER (PARTITION BY channel) AS time_share
FROM tag_time
ORDER BY channel, tag;
