class SectorPeerService:
    _groups = {
        "Água e saneamento": ("SAPR4", "SBSP3", "CSMG3"),
        "Bancos": ("BBAS3", "ITUB4", "BBDC4", "SANB11"),
        "Holdings financeiras": ("ITSA4", "ITUB4", "BBAS3", "BBDC4"),
        "Seguros": ("BBSE3", "PSSA3", "CXSE3"),
        "Petróleo e gás": ("PETR4", "PRIO3", "RECV3", "BRAV3"),
        "Transmissão de energia": ("TAEE11", "ISAE4", "ALUP11"),
        "Energia elétrica": ("CMIG4", "CPFE3", "CPLE6", "EGIE3", "ELET3", "ENGI11"),
    }

    def get_peers(self, ticker: str) -> tuple[str | None, list[str]]:
        normalized = ticker.strip().upper()
        for sector, members in self._groups.items():
            if normalized in members:
                peers = [member for member in members if member != normalized][:3]
                return sector, peers
        return None, []
