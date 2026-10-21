-- Gold build for dim_school_location (#217, docs/architecture/data-model.md).
--
-- One row per public school with a published location: every row of deped_school_boundary_map (Integration),
-- which has one row per school of deped_psgc_coordinates_clean (the public-only DepEd workbook, SY 2023-24;
-- coordinates from NSBI as of 2025-07-07) and the boundary test S-1 at city or municipality level. It joins
-- dim_school on school_id, one to zero or one, and carries no PSGC code: a school's city and barangay come only
-- from deped_school_psgc_map through the facts (D-049), so there is one path from a school to its LGU.
--
-- Reads the published map only. Writes dim_school_location_candidate; the gate (the next task) checks it and
-- publishes dim_school_location only if no check fails. It rebuilds on every run. The spatial work is the map's,
-- so this build is a projection: longitude, latitude, coordinate_flag and boundary_status are the map's,
-- unchanged. Only boundary_status = 'inside' is fit for a map (D-061, proposed).

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_location_candidate USING DELTA AS
SELECT school_id, longitude, latitude, coordinate_flag, boundary_status
FROM edu_access.`04-integration`.deped_school_boundary_map
WHERE school_year = '2023-24';

ALTER TABLE edu_access.`05-gold`.dim_school_location_candidate OWNER TO `reached-hq`;
