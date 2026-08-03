from app.services.repository import SourceRepository


def test_source_repository_exposes_read_methods_only():
    public={name for name in dir(SourceRepository) if not name.startswith('_')}
    assert 'fetch_snapshots_after' in public
    assert 'latest_snapshot_time' in public
    for forbidden in {'insert','upsert','patch','rpc','delete'}:
        assert forbidden not in public
