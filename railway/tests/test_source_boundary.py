from app.services.repository import ReadOnlyRestClient, SourceRepository


def test_source_repository_exposes_read_methods_only():
    public={name for name in dir(SourceRepository) if not name.startswith('_')}
    assert {'fetch_snapshots_after','latest_snapshot_time','fetch_candles_page'} <= public
    for forbidden in {'insert','upsert','patch','rpc','delete'}:
        assert forbidden not in public


def test_source_http_client_has_no_write_surface():
    public={name for name in dir(ReadOnlyRestClient) if not name.startswith('_')}
    assert 'get' in public
    for forbidden in {'insert','upsert','patch','rpc','delete','post'}:
        assert forbidden not in public
