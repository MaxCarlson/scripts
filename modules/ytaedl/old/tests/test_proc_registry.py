from ytaedl.downloaders import terminate_all_active_procs

def test_terminate_all_active_procs_noop():
    # Should not raise when nothing is registered
    terminate_all_active_procs()
