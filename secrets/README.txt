Drop the Google Earth Engine service-account JSON here as gee_service_account.json.
This directory is mounted read-only into the backend and worker containers.
Without it, satellite features report UNAVAILABLE; everything else still runs.
