from viral_finder.system_observer import SystemObserver

def test_observer_none_timestamps():
    obs = SystemObserver()
    
    # 1. Log a stage to populate stages info
    obs.log_stage(
        name="TEST_STAGE",
        input_count=5,
        output_count=2,
        wall_time=0.45,
        reject_reasons={"low_score": 3}
    )
    
    # 2. Register candidate with None start and None end times
    obs.init_candidate(
        cid="cand_1",
        created_by="test_run",
        text="A test candidate with no start or end",
        start=None,
        end=None,
        scores={"score": 0.85}
    )
    
    # 3. Call render_report and assert it succeeds
    report = obs.render_report()
    
    assert report is not None
    assert "N/A - N/A" in report
    assert "TEST_STAGE" in report
    assert "cand_1" in report
