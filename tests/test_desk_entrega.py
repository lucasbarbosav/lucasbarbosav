"""Testes da classificação de entrega da informação (fixtures sintéticas).

Cada fixture replica um padrão visto em produção e documentado em
`docs/desk_calibracao.md`:

- retorno da área por e-mail no Desk + bounce ao avisar o cliente (#1491212);
- resposta ao cliente sem retorno interno — entrega fora do Desk (#1128567);
- pendência marcada mas nunca disparada, sem retorno (#1128254);
- retorno da área por comentário privado entre agentes (#1352645);
- threads duplicadas, resposta automática e bounce como ruído a excluir.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.desk_entrega import (  # noqa: E402
    classificar,
    conteudo_informativo,
    eh_interno,
    normalizar_conversas,
)

T = "2026-08-20T19:51:37.000Z"


def _thread(tempo, direcao, de, para="", texto="", autor_tipo="AGENT", desc=False, id=""):
    return {
        "type": "thread", "createdTime": tempo, "direction": direcao,
        "isDescriptionThread": desc, "summary": texto,
        "author": {"type": autor_tipo, "email": de if autor_tipo == "AGENT" else None},
        "fromEmailAddress": f"<{de}>", "to": para, "cc": "", "id": id or f"t{tempo}{direcao}",
    }


def _comentario(tempo, de, texto, id=""):
    return {
        "type": "comment", "commentedTime": tempo, "content": texto,
        "commenter": {"type": "AGENT", "email": de}, "id": id or f"c{tempo}",
    }


def _ticket(criado=T):
    return {"ticket_id": "1", "criado_em": criado, "cf_area_pi": "Operacional"}


def test_dominio_interno():
    assert eh_interno("trafego.blm@expressoguanabara.com.br")
    assert eh_interno("plantaocomercial@realexpresso.com.br")
    assert eh_interno("mateus.agra@util.com.br")
    assert not eh_interno("cliente@gmail.com")
    assert not eh_interno("")


def test_conteudo_informativo():
    assert conteudo_informativo("Na referida data houve a sobra de uma bolsa vermelha") == "info"
    assert conteudo_informativo("Infelizmente o objeto NÃO foi localizado após as buscas") == "info"
    assert conteudo_informativo(
        "Recebemos o seu contato, que gerou o protocolo 123. Retornaremos em breve!"
    ) == "ack"
    assert conteudo_informativo("Obrigado pelo carinho, abraços") == "incerto"


def test_entregue_no_desk_com_bounce_ao_cliente():
    """#1491212: pendência 90h depois da abertura; área responde em minutos;
    aviso ao cliente volta (bounce). Threads internas vêm DUPLICADAS."""
    conversas = [
        _thread(T, "in", "cliente@gmail.com", texto="Perdi minha mochila",
                autor_tipo="END_USER", desc=True),
        _thread("2026-08-24T13:40:51.000Z", "out", "sac@viajeguanabara.com.br",
                para="filial.blm@expressoguanabara.com.br,achadoseperdidosmatriz@viajeguanabara.com.br",
                texto="PENDÊNCIA INTERNA Olá! Aqui vão as informações para a sua análise"),
        _thread("2026-08-24T14:04:51.000Z", "in", "trafego.blm@expressoguanabara.com.br",
                texto="Houve a sobra de uma bolsa vermelha, peço a confirmação",
                autor_tipo="", id="dup1"),
        _thread("2026-08-24T14:04:51.000Z", "in", "trafego.blm@expressoguanabara.com.br",
                texto="Houve a sobra de uma bolsa vermelha, peço a confirmação",
                autor_tipo="", id="dup2"),
        _thread("2026-08-24T14:17:16.000Z", "out", "sac@viajeguanabara.com.br",
                para="cliente@gmail.com", texto="Identificamos um objeto, segue a foto em anexo"),
        _thread("2026-08-24T14:18:12.000Z", "in", "mailer-daemon@mail.zoho.com",
                texto="This message was created automatically by mail delivery software. "
                      "could not be delivered", autor_tipo=""),
    ]
    eventos = normalizar_conversas(conversas)
    assert len(eventos) == 5, "thread interna duplicada deveria ser deduplicada"
    c = classificar(_ticket(), eventos)
    assert c.estado == "entregue_no_desk"
    assert c.canal_da_resposta == "email_interno"
    assert c.disparo_no_desk
    assert c.retorno_cliente_falhou
    assert 89 < c.latencia_disparo_h < 91
    assert 0.3 < c.latencia_area_h < 0.5


def test_entregue_fora_do_desk():
    """#1128567: macro de pendência disparada e, minutos depois, resposta ao
    cliente com a informação — sem nenhum retorno interno registrado."""
    conversas = [
        _thread(T, "in", "cliente@gmail.com", texto="Fui trocado de leito para executivo",
                autor_tipo="END_USER", desc=True),
        _thread("2026-08-21T17:38:42.000Z", "out", "sac@viajeguanabara.com.br",
                para="plantaocomercial@realexpresso.com.br,trafego.comercial@util.com.br",
                texto="PENDÊNCIA INTERNA segue reclamação para análise"),
        _thread("2026-08-21T17:42:44.000Z", "out", "sac@viajeguanabara.com.br",
                para="cliente@gmail.com",
                texto="Informamos que, por motivos operacionais, foi necessária a troca do veículo"),
    ]
    c = classificar(_ticket(), normalizar_conversas(conversas))
    assert c.estado == "entregue_fora_do_desk"
    assert c.canal_da_resposta == "cliente"
    assert c.disparo_no_desk


def test_nao_entregue_sem_disparo():
    """#1128254: cf_area_pi preenchido, mas nada foi disparado nem respondido.
    Resposta automática e template de recebimento não contam como entrega."""
    conversas = [
        _thread(T, "in", "cliente@gmail.com", texto="Reclamação de categoria inferior",
                autor_tipo="END_USER", desc=True),
        _thread("2026-08-20T19:52:00.000Z", "out", "sac@viajeguanabara.com.br",
                para="cliente@gmail.com",
                texto="Resposta Automática Olá! Recebemos o seu contato, que gerou o protocolo 1"),
        _thread("2026-08-21T10:00:00.000Z", "out", "sac@viajeguanabara.com.br",
                para="cliente@gmail.com",
                texto="Sua solicitação foi registrada, retornaremos em breve"),
    ]
    c = classificar(_ticket(), normalizar_conversas(conversas))
    assert c.estado == "nao_entregue"
    assert not c.disparo_no_desk


def test_entregue_no_desk_via_comentario():
    """#1352645: pedido e retorno circulam como comentários entre agentes;
    o retorno vem de OUTRO agente, com o conteúdo pedido."""
    conversas = [
        _thread(T, "in", "agencia@gmail.com", texto="Solicitação de estorno",
                autor_tipo="END_USER", desc=True),
        _comentario("2026-08-21T17:27:00.000Z", "naiane.lopes@viajeguanabara.com.br",
                    "Márcia, boa tarde! Gentileza seguir com o estorno abaixo"),
        _comentario("2026-08-22T14:15:00.000Z", "comercial.civil@viajeguanabara.com.br",
                    "Lançado pedido de estorno, prazo de processamento é de até 48 horas"),
    ]
    c = classificar(_ticket(), normalizar_conversas(conversas))
    assert c.estado == "entregue_no_desk"
    assert c.canal_da_resposta == "comentario"
    assert c.disparo_no_desk
    assert 20 < c.latencia_area_h < 21


def test_ambiguo_vai_para_fila_llm():
    conversas = [
        _thread(T, "in", "cliente@gmail.com", texto="Cadê minha mala?",
                autor_tipo="END_USER", desc=True),
        _thread("2026-08-21T17:38:42.000Z", "out", "sac@viajeguanabara.com.br",
                para="achadoseperdidosmatriz@viajeguanabara.com.br",
                texto="PENDÊNCIA INTERNA verificar objeto"),
        _thread("2026-08-22T09:00:00.000Z", "out", "sac@viajeguanabara.com.br",
                para="cliente@gmail.com",
                texto="Olá! Estamos cuidando do seu caso com muito carinho, obrigado"),
    ]
    c = classificar(_ticket(), normalizar_conversas(conversas))
    assert c.estado == "indeterminado"
    assert c.precisa_llm
    assert c.pendencia_llm["tipo"] == "cliente"


def test_auto_resposta_interna_nao_e_disparo():
    """Auto-reply para endereço interno (agência abriu o ticket) não pode ser
    lida como disparo de pendência (#1352645 tinha exatamente isso)."""
    conversas = [
        _thread(T, "in", "agencia@gmail.com", texto="Estorno", autor_tipo="END_USER", desc=True),
        _thread("2026-08-20T19:51:45.000Z", "out", "sac@viajeguanabara.com.br",
                para="josimar.ibiapina@viajeguanabara.com.br",
                texto="Resposta Automática Olá, agente, recebemos o seu contato, "
                      "que gerou o protocolo 1"),
    ]
    c = classificar(_ticket(), normalizar_conversas(conversas))
    assert c.estado == "nao_entregue"
    assert not c.disparo_no_desk


def test_paineis_renderizam():
    """Fumaça dos painéis: fixture sintética em diretório temporário."""
    import random

    from src import _common, charts, desk_charts

    rng = random.Random(7)
    estados = ["entregue_no_desk", "entregue_fora_do_desk", "indeterminado", "nao_entregue"]
    areas = ["Comercial", "Operacional", "Financeiro", "Manutenção"]
    linhas = []
    for i in range(400):
        e = rng.choices(estados, weights=[45, 15, 15, 25])[0]
        linhas.append({
            "ticket_id": str(i), "ticket_numero": str(1_000_000 + i),
            "criado_em": "2026-05-01T12:00:00.000Z",
            "area": rng.choice(areas), "assunto": rng.choice(
                ["Achados e Perdidos", "Categoria inferior", "Atraso", "Depósito"]),
            "solucao": None, "status": "Fechado", "status_tipo": "Closed",
            "canal": "0800", "estado": e, "disparo_no_desk": e != "nao_entregue",
            "canal_da_resposta": "email_interno" if e == "entregue_no_desk" else "",
            "latencia_disparo_h": rng.uniform(1, 120),
            "latencia_area_h": rng.uniform(0.2, 90) if e == "entregue_no_desk" else None,
            "retorno_cliente_falhou": rng.random() < 0.05,
            "precisa_llm": e == "indeterminado" and rng.random() < 0.5,
            "evidencia": "trecho sintético de evidência" if "entregue" in e else "",
            "evidencia_id": "",
        })
    df = pd.DataFrame(linhas)

    with tempfile.TemporaryDirectory() as tmp:
        limpo = Path(tmp) / "clean"; limpo.mkdir()
        saida = Path(tmp) / "charts"; saida.mkdir()
        resumo_dir = Path(tmp) / "desk"
        df.to_parquet(limpo / "desk_entrega_classificada.parquet", index=False)
        (limpo / "desk_entrega_classificada.meta.json").write_text(json.dumps(asdict(
            _common.Proveniencia(
                fonte="FIXTURE SINTETICA (teste)", url="https://exemplo.invalido",
                data_extracao="2026-08-24T12:00:00-03:00", n_registros=len(df),
                arquivo="x", ano_base="2026",
            ))), encoding="utf-8")

        orig = _common.DATA_CLEAN, charts.CHARTS, desk_charts.OUT_DESK
        _common.DATA_CLEAN, charts.CHARTS, desk_charts.OUT_DESK = limpo, saida, resumo_dir
        try:
            resultado = desk_charts.executar()
        finally:
            _common.DATA_CLEAN, charts.CHARTS, desk_charts.OUT_DESK = orig

        assert not resultado["pulados"], f"painéis pulados: {resultado['pulados']}"
        pngs = sorted(p.name for p in saida.glob("*.png"))
        assert len(pngs) == len(desk_charts.PAINEIS), pngs
        for p in saida.glob("*.png"):
            assert p.stat().st_size > 10_000, f"{p.name} pequeno demais"
        texto = (resumo_dir / "resumo.md").read_text(encoding="utf-8")
        assert "PISO DE INCERTEZA" in texto and "Por área acionada" in texto
        print(f"    {len(pngs)} PNGs + resumo.md OK")


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
