from app.services.sector_peer_service import SectorPeerService


def test_sapr4_returns_same_sector_peers():
    sector, peers = SectorPeerService().get_peers("sapr4")

    assert sector == "Água e saneamento"
    assert peers == ["SBSP3", "CSMG3"]


def test_unknown_ticker_has_no_sector_peers():
    assert SectorPeerService().get_peers("VALE3") == (None, [])
