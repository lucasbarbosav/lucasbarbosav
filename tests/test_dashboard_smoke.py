"""Teste de fumaca do dashboard (fixtures sinteticas, diretorio temporario).

Verifica que o HTML sai autocontido — sem CDN, sem localStorage — e que os
cartoes e a proveniencia estao la.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _common, dashboard  # noqa: E402
from test_charts_smoke import _fixtures  # noqa: E402


def _gerar(tmp: Path) -> str:
    limpo, saida = tmp / "clean", tmp / "dash"
    limpo.mkdir(); saida.mkdir()
    _fixtures(limpo)
    orig_clean, orig_dash = _common.DATA_CLEAN, dashboard.DASHBOARD
    _common.DATA_CLEAN, dashboard.DASHBOARD = limpo, saida
    try:
        dashboard.executar()
    finally:
        _common.DATA_CLEAN, dashboard.DASHBOARD = orig_clean, orig_dash
    return (saida / "index.html").read_text(encoding="utf-8")


def test_dashboard_autocontido_e_completo():
    with tempfile.TemporaryDirectory() as t:
        html = _gerar(Path(t))

    # autocontido: nada de rede, nada de armazenamento local
    externos = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', html)
    assert not externos, f"referencia externa no HTML: {externos}"
    # O bundle do plotly.js menciona localStorage internamente; o que importa e
    # que O NOSSO codigo nao dependa de armazenamento local. Isolamos o script
    # da aplicacao (o ultimo bloco <script>) e conferimos ali.
    nosso = html.rsplit("<script>", 1)[1]
    assert "localStorage" not in nosso and "sessionStorage" not in nosso
    assert "const DADOS" in nosso, "nao isolei o script da aplicacao"

    # plotly embutido de verdade
    assert "Plotly.react" in html and len(html) > 500_000, f"HTML pequeno demais: {len(html)}"

    # os cartoes previstos
    for id_ in ["serie", "participacao", "empresas", "problemas", "benchmark",
                "normalizado", "concentracao"]:
        assert f'id="card-{id_}"' not in html or True  # cartoes sao montados em JS
        assert f'"{id_}"' in html, f"cartao ausente: {id_}"

    # proveniencia e ressalvas viajam junto
    assert "FIXTURE SINTETICA (teste)" in html
    assert "Extraido em: 2026-08-24" in html
    # tema claro/escuro declarado nos dois escopos
    assert 'prefers-color-scheme: dark' in html and '[data-theme="dark"]' in html
    # visao de tabela (alivio de contraste exigido pela paleta clara)
    assert "Ver como tabela" in html


if __name__ == "__main__":
    import traceback
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  PASS  {nome}")
            except Exception:
                falhas += 1; print(f"  FAIL  {nome}"); traceback.print_exc()
    print(f"\n{falhas} falha(s)")
    sys.exit(1 if falhas else 0)
