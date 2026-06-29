# generator.py
import json, zlib, base64, secrets, datetime as dt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 32 bytes de segredo do servidor (guarde fora do código!)
SECRET_KEY = base64.urlsafe_b64decode("Q2hhbmdlRXN0ZVNlZ3JlZG8zMkJ5dGVzIT8hIS0xMjM0NTY=")[:32]

PLANOS = {
    "DEMO_7D": 7, "MENSAL_30D": 30, "TRI_90D": 90, "SEM_180D": 180, "ANUAL_365D": 365, "TEST_14D": 14
}

def gerar_licenca(plano: str|None=None, dias: int|None=None, device_id: str|None=None) -> bytes:
    # defina o número de dias
    if dias is None:
        if not plano or plano not in PLANOS:
            raise ValueError("Informe um plano válido ou 'dias'")
        dias_final = PLANOS[plano]
        plano_label = plano
    else:
        if dias <= 0:
            raise ValueError("'dias' deve ser > 0")
        dias_final = int(dias)
        plano_label = plano or f"CUSTOM_{dias_final}D"

    hoje = dt.datetime.utcnow()
    payload = {
        "lic_id": secrets.token_hex(8),
        "plano": plano_label,
        "emitido_em": hoje.isoformat() + "Z",
        "expira_em": (hoje + dt.timedelta(days=dias_final)).isoformat() + "Z",
        "device_id": device_id,
        "versao": 1,
    }

    comp = zlib.compress(json.dumps(payload, separators=(',', ':')).encode(), level=9)
    aes = AESGCM(SECRET_KEY)
    iv = secrets.token_bytes(12)
    ct = aes.encrypt(iv, comp, b"UNISYSTEM_LIC_V1")  # AAD
    return b"ULIC\x01" + iv + ct  # header + IV + ciphertext+tag

# exemplos de uso
if __name__ == "__main__":
    # usando o plano
    #lic1 = gerar_licenca(plano="DEMO_7D")
    #with open("lic_plano.lic", "wb") as f: f.write(lic1)

    #usando dias customizados (ex.: 45 dias)
    lic2 = gerar_licenca(dias=1)
    with open("lic_45d.lic", "wb") as f: f.write(lic2)
