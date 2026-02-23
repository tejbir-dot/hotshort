TIERS = {
    "free": {
        "clips_per_week": 3,
        "max_clips_per_job": 3,
        "watermark": True,
        "fast_render": False,
        "narrative_ai": False,
        "cosmo_ai": False
    },

    "pro": {
        "clips_per_week": 999,
        "max_clips_per_job": 12,
        "watermark": False,
        "fast_render": True,
        "narrative_ai": True,
        "cosmo_ai": False
    },

    "creator": {
        "clips_per_week": 999,
        "max_clips_per_job": 20,
        "watermark": False,
        "fast_render": True,
        "narrative_ai": True,
        "cosmo_ai": True
    }
}
