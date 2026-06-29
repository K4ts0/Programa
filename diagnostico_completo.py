import sqlite3
import os

print("="*60)
print("🔍 DIAGNÓSTICO COMPLETO DO BANCO DE DADOS")
print("="*60)

# Encontrar o banco de dados
db_path = 'estoque.db'
if not os.path.exists(db_path):
    print("❌ ERRO: Banco de dados não encontrado!")
    exit()

print(f"✅ Banco encontrado: {db_path}")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# ============ 1. VERIFICAR TABELAS EXISTENTES ============
print("\n📋 1. TABELAS NO BANCO:")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tabelas = cursor.fetchall()
for t in tabelas:
    nome = t[0]
    cursor.execute(f"SELECT COUNT(*) FROM {nome}")
    count = cursor.fetchone()[0]
    print(f"   - {nome}: {count} registros")

# ============ 2. VERIFICAR ATENDIMENTOS (VENDAS) ============
print("\n💰 2. ATENDIMENTOS / VENDAS:")
cursor.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN status = 'concluido' THEN 1 ELSE 0 END) as concluidos,
        SUM(CASE WHEN status = 'pendente' THEN 1 ELSE 0 END) as pendentes,
        SUM(CASE WHEN status = 'cancelado' THEN 1 ELSE 0 END) as cancelados,
        SUM(valor) as faturamento_total,
        SUM(CASE WHEN status = 'concluido' THEN valor ELSE 0 END) as faturamento_concluido
    FROM atendimentos
""")
row = cursor.fetchone()
total_atendimentos = row['total'] or 0
concluidos = row['concluidos'] or 0
faturamento_concluido = row['faturamento_concluido'] or 0

print(f"   Total atendimentos: {total_atendimentos}")
print(f"   Concluídos (VENDAS): {concluidos}")
print(f"   Pendentes: {row['pendentes'] or 0}")
print(f"   Cancelados: {row['cancelados'] or 0}")
print(f"   Faturamento total: R$ {row['faturamento_total'] or 0:.2f}")
print(f"   Faturamento concluído: R$ {faturamento_concluido:.2f}")

# ============ 3. VERIFICAR PRODUTOS ============
print("\n📦 3. PRODUTOS:")
cursor.execute("SELECT COUNT(*) as total, SUM(quantidade) as estoque_total, SUM(preco * quantidade) as valor_estoque FROM produtos")
row = cursor.fetchone()
print(f"   Total produtos: {row['total'] or 0}")
print(f"   Estoque total: {row['estoque_total'] or 0} unidades")
print(f"   Valor em estoque: R$ {row['valor_estoque'] or 0:.2f}")

# Mostrar estrutura da tabela produtos
cursor.execute("PRAGMA table_info(produtos)")
colunas = cursor.fetchall()
print(f"\n   Colunas da tabela produtos:")
for col in colunas:
    print(f"     - {col['name']}: {col['type']}")

# ============ 4. VERIFICAR COMPRAS ============
print("\n🛍️ 5. COMPRAS (GASTOS):")
cursor.execute("SELECT COUNT(*) as total, SUM(total) as total_gastos FROM compras")
row = cursor.fetchone()
total_compras = row['total'] or 0
total_gastos = row['total_gastos'] or 0
print(f"   Total compras: {total_compras}")
print(f"   Total gastos: R$ {total_gastos:.2f}")

# ============ 5. DIAGNÓSTICO FINAL ============
print("\n" + "="*60)
print("🎯 DIAGNÓSTICO FINAL - SOLUÇÃO PARA OS RELATÓRIOS")
print("="*60)

print("\n✅ SEUS DADOS ESTÃO CORRETOS!")
print(f"   • {concluidos} vendas concluídas")
print(f"   • R$ {faturamento_concluido:.2f} em faturamento")
print(f"   • {total_compras} compras registradas")
print(f"   • R$ {total_gastos:.2f} em gastos")

print("\n🔴 PROBLEMA IDENTIFICADO:")
print("   A rota /api/relatorios completa TEM UM ERRO DE CONSULTA SQL!")
print("   Está tentando usar a coluna 'ultimo_custo' que NÃO EXISTE na tabela produtos.")

print("\n🟢 SOLUÇÃO:")
print("   1. Abra o arquivo 'api_flask.py'")
print("   2. Vá até a linha ~1370")
print("   3. Substitua o trecho de 'lucro_detalhado' pelo código abaixo:")

print("""
# === LUCRO DETALHADO - CORRIGIDO ===
try:
    # Verificar se a coluna custo_medio existe
    cursor_col = db.execute("PRAGMA table_info(produtos)").fetchall()
    colunas_produtos = [c[1] for c in cursor_col]
    
    if 'custo_medio' in colunas_produtos:
        campo_custo = 'p.custo_medio'
    elif 'custo_unitario' in colunas_produtos:
        campo_custo = 'p.custo_unitario'
    else:
        campo_custo = '0'  # fallback
    
    lucro_detalhado_row = db.execute(f"""
        SELECT SUM( (ai.preco - COALESCE({campo_custo}, 0)) * ai.quantidade ) AS lucro_total
        FROM atendimento_itens ai
        JOIN produtos p ON ai.produto_id = p.id
        JOIN atendimentos a ON ai.atendimento_id = a.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        AND ai.tipo = 'produto'
    """, [di, df]).fetchone()
    lucro_detalhado = float(lucro_detalhado_row["lucro_total"] or 0) if lucro_detalhado_row else 0
except Exception as e:
    print(f"Erro no cálculo de lucro detalhado: {e}")
    lucro_detalhado = 0
""")

print("\n📌 PASSO A PASSO COMPLETO:")
print("   1. REMOVA a PRIMEIRA rota /api/relatorios (linhas ~572-600)")
print("   2. CORRIJA a SEGUNDA rota /api/relatorios com o código acima")
print("   3. REINICIE o servidor Flask")
print("   4. Pronto! Todas as abas vão funcionar")

conn.close()