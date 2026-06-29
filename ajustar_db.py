import sqlite3

DB_PATH = "estoque.db"

def corrigir_banco():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # === Corrige produtos (se não tiver as colunas) ===
    try:
        cur.execute("ALTER TABLE produtos ADD COLUMN custo_medio REAL DEFAULT 0;")
        print("[OK] Coluna 'custo_medio' adicionada.")
    except Exception as e:
        print("[INFO] coluna custo_medio já existe:", e)

    try:
        cur.execute("ALTER TABLE produtos ADD COLUMN ultimo_custo REAL DEFAULT 0;")
        print("[OK] Coluna 'ultimo_custo' adicionada.")
    except Exception as e:
        print("[INFO] coluna ultimo_custo já existe:", e)

    # === Cria tabela compras se não existir ===
    cur.execute("""
    CREATE TABLE IF NOT EXISTS compras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL CHECK (tipo IN ('produto','servico','outro')),
        produto_id INTEGER,
        descricao TEXT,
        quantidade INTEGER DEFAULT 1,
        custo_unitario REAL NOT NULL,
        total REAL NOT NULL,
        forma_pagamento TEXT,
        data TEXT NOT NULL,
        observacao TEXT,
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    )
    """)
    print("[OK] Tabela 'compras' garantida.")

    con.commit()
    con.close()
    print("? Correções aplicadas com sucesso no banco:", DB_PATH)

if __name__ == "__main__":
    corrigir_banco()
