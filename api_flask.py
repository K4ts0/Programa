from flask import (
    Flask, request, jsonify, send_file, send_from_directory,
    g, render_template, redirect, url_for, session
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from datetime import datetime, timedelta
from dateutil import parser
from decimal import Decimal, ROUND_HALF_UP, getcontext
import sqlite3, io, os, json, pytz
from functools import wraps
import base64, zlib, datetime as dt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytz
    
getcontext().prec = 28

app = Flask(__name__)
app.jinja_env.globals.update(datetime=datetime)
@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave")
CORS(app)

# topo do arquivo
import zipfile, hashlib, tempfile, re

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

# === LICENÇA (NOVO) – substitui TODO o PASSO 1 antigo =======================
# Mantido apenas por compatibilidade (NÃO é usado no novo sistema):
LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "compat-not-used")

# Chave AES (32 bytes) – em produção, use variável de ambiente LICENSE_AES_KEY
SECRET_KEY = base64.urlsafe_b64decode(
    os.environ.get("LICENSE_AES_KEY", "Q2hhbmdlRXN0ZVNlZ3JlZG8zMkJ5dGVzIT8hIS0xMjM0NTY=")
)[:32]
AAD = b"UNISYSTEM_LIC_V1"
HEADER = b"ULIC\x01"

def validar_licenca(lic_bytes: bytes):
    if not lic_bytes.startswith(HEADER):
        raise ValueError("Arquivo .lic inválido")
    iv, ct = lic_bytes[5:17], lic_bytes[17:]
    comp = AESGCM(SECRET_KEY).decrypt(iv, ct, AAD)
    data = json.loads(zlib.decompress(comp).decode())
    exp = dt.datetime.fromisoformat(data["expira_em"].replace("Z",""))
    ok = dt.datetime.utcnow() <= exp
    return ok, data

def agora_sp():
    return datetime.now(pytz.timezone("America/Sao_Paulo"))

def licenca_status_db():
    db = get_db()
    row = db.execute("""
        SELECT id, tipo, chave_hash, ativado_em, expira_em, status
        FROM licenca WHERE id=1
    """).fetchone()
    if not row:
        return {"ativa": False, "tipo": None, "expira_em": None, "dias_restantes": None}
    tipo = row["tipo"]; expira_em = row["expira_em"]
    if tipo == "VITALICIO":
        return {"ativa": True, "tipo": tipo, "expira_em": None, "dias_restantes": None}
    if not expira_em:
        return {"ativa": False, "tipo": tipo, "expira_em": None, "dias_restantes": None}
    try:
        exp = parser.isoparse(expira_em)
    except Exception:
        return {"ativa": False, "tipo": tipo, "expira_em": expira_em, "dias_restantes": None}
    ativa = agora_sp() <= exp.astimezone(pytz.timezone("America/Sao_Paulo"))
    dias_restantes = max(0, (exp.date() - agora_sp().date()).days)
    return {"ativa": bool(ativa), "tipo": tipo, "expira_em": expira_em, "dias_restantes": dias_restantes}

def licenca_ativa():
    return licenca_status_db().get("ativa", False)

DATABASE = 'estoque.db'  
CONFIG_FILE = "config.json"
CONFIG_PATH = "config.json"
UPLOAD_FOLDER = 'static/imagens'

# --- aqui você cola o login_required ---
def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

def nivel_atual():
    return (session.get("nivel") or "FUNCIONARIO").upper()

def exige_login(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("user_id"):
            return jsonify({"error":"login requerido"}), 401
        return fn(*a, **k)
    return w

def exige_nivel(*permitidos):
    permitidos = {p.upper() for p in permitidos}
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not session.get("user_id"):
                return jsonify({"error":"login requerido"}), 401
            if nivel_atual() not in permitidos:
                return jsonify({"error":"sem permissão"}), 403
            return fn(*a, **k)
        return w
    return deco

def require_nivel(*permitidos):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            if not session.get("user_id"):
                return redirect(url_for("login", next=request.path))
            if session.get("nivel") not in permitidos:
                return ("Acesso negado", 403)
            return fn(*a, **kw)
        return inner
    return deco

def user_nivel():
    return (session.get("nivel") or "FUNCIONARIO").upper()

# --- Rotas da API de licença ---
@app.route("/api/licenca", methods=["GET"])
@exige_login
def api_licenca_get():
    return jsonify(licenca_status_db())

# Rotas para as páginas HTML
@app.route('/atendimento')
@login_required
def pagina_atendimento():
    return render_template(
        'atendimento.html',
        usuario_nome=session.get('nome', 'Atendente')  # <- ADICIONE ESTA LINHA
    )

@app.route('/relatorios')
@login_required
@require_nivel('ADMIN')        # só admin vê relatórios
def pagina_relatorios():
    return render_template('gerarrelatorios.html')

@app.route('/estoque')
@login_required
def pagina_estoque():
    return render_template('estoque.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("home"))
        return render_template("login.html")

    usuario = (request.form.get("usuario") or "").strip()
    senha = request.form.get("senha") or ""

    db = get_db()
    row = db.execute(
        "SELECT id, senha_hash, nivel, nome, "
        "COALESCE(desabilitado,0) AS desabilitado, "
        "COALESCE(sess_rev,0) AS sess_rev "
        "FROM usuarios WHERE usuario=?",
        (usuario,)
    ).fetchone()


    if not row or not check_password_hash(row["senha_hash"], senha):
        return redirect(url_for("login", erro=1))

    # 🚫 bloqueio de usuário desativado
    if row["desabilitado"]:
        return redirect(url_for("login", erro=2))

    session["user_id"]  = row["id"]
    session["usuario"]  = usuario
    session["nivel"]    = (row["nivel"] or "FUNCIONARIO").upper()
    session["nome"]     = row["nome"] or ""
    session["sess_rev"] = row["sess_rev"]
    return redirect(request.args.get("next") or url_for("home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# Rota /
@app.route("/")
@login_required
def home():
    return render_template(
        "home.html",
        usuario=session.get("usuario"),
        nivel=(session.get("nivel") or "FUNCIONARIO").upper(),
        lic=licenca_status_db(),
        agora=now_br()   # <— ADICIONADO
    )

def now_br():
    return datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON;')
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT,
            nome TEXT NOT NULL,
            marca TEXT,
            descricao TEXT,
            preco REAL NOT NULL,
            quantidade INTEGER NOT NULL,
            categoria TEXT,
            data_cadastro TEXT DEFAULT (datetime('now', 'localtime')),
            imagem TEXT
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            preco REAL NOT NULL,
            data_cadastro TEXT DEFAULT (datetime('now', 'localtime'))
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            contato TEXT NOT NULL,
            bairro TEXT NOT NULL,
            data_cadastro TEXT NOT NULL
        )''')

        # ALTERAÇÃO: inclui tipo_atendimento
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS atendimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            atendente TEXT NOT NULL,
            tipo_servico TEXT NOT NULL,
            produto_id INTEGER,
            valor REAL NOT NULL,
            forma_pagamento TEXT NOT NULL,
            observacoes TEXT,
            status TEXT NOT NULL,
            data_inicio TEXT NOT NULL,
            data_fim TEXT,
            tempo_servico REAL,
            tipo_atendimento TEXT DEFAULT 'atendimento',
            FOREIGN KEY (cliente_id) REFERENCES clientes(id),
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')
        # ALTER TABLE caso a coluna não exista (caso já tenha o banco criado)
        try:
            cursor.execute("ALTER TABLE atendimentos ADD COLUMN tipo_atendimento TEXT DEFAULT 'atendimento';")
        except Exception:
            pass

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimentacao_estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            produto_nome TEXT,       -- <--- ADICIONE ESTA LINHA
            tipo TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            data TEXT NOT NULL,
            observacao TEXT,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')


        cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_precos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            preco_antigo REAL NOT NULL,
            preco_novo REAL NOT NULL,
            data_alteracao TEXT NOT NULL,
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT
        )''')
        db.commit()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS atendimento_servicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atendimento_id INTEGER NOT NULL,
            servico_id INTEGER NOT NULL,
            quantidade INTEGER DEFAULT 1,
            FOREIGN KEY (atendimento_id) REFERENCES atendimentos(id),
            FOREIGN KEY (servico_id) REFERENCES servicos(id)
        )''')

        db.commit()
    
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS notas_fiscais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT,
            serie TEXT,
            data_emissao TEXT,
            tipo_operacao TEXT,
            natureza_operacao TEXT,
            emitente_nome TEXT,
            emitente_cnpj TEXT,
            emitente_ie TEXT,
            emitente_endereco TEXT,
            destinatario_nome TEXT,
            destinatario_cnpj TEXT,
            destinatario_ie TEXT,
            destinatario_endereco TEXT,
            valor_total REAL,
            desconto REAL,
            frete REAL,
            seguro REAL,
            outras_despesas REAL,
            total_impostos REAL,
            tipo_frete TEXT,
            transportadora TEXT,
            placa_veiculo TEXT,
            uf_veiculo TEXT,
            quantidade_volumes INTEGER,
            informacoes_complementares TEXT,
            forma_pagamento TEXT,
            data_cadastro TEXT DEFAULT (datetime('now', 'localtime'))
        )''')

        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS notas_fiscais_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nota_id INTEGER,
            codigo_produto TEXT,
            descricao TEXT,
            ncm TEXT,
            quantidade INTEGER,
            unidade TEXT,
            valor_unitario REAL,
            valor_total REAL,
            cfop TEXT,
            icms REAL,
            ipi REAL,
            pis REAL,
            cofins REAL,
            FOREIGN KEY (nota_id) REFERENCES notas_fiscais(id)
        )''')

        db.commit()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS registro_exclusoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entidade TEXT NOT NULL,           -- 'produto' ou 'servico'
            item_id INTEGER NOT NULL,
            item_nome TEXT NOT NULL,
            quantidade INTEGER,               -- pode ser null para serviço
            usuario TEXT,                     -- quem fez a exclusão
            data_hora TEXT NOT NULL,          -- data e hora no formato ISO
            observacao TEXT
        )
        ''')
        db.commit()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS atendimento_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atendimento_id INTEGER NOT NULL,
            produto_id INTEGER,
            servico_id INTEGER,
            quantidade INTEGER,
            preco REAL,
            tipo TEXT
        )
        ''')

        db.commit()  # <--- COMMIT após criar as tabelas

        # ALTER TABLES (rodar após criar as tabelas, para corrigir bancos antigos!)
        try:
            cursor.execute("ALTER TABLE movimentacao_estoque ADD COLUMN produto_nome TEXT;")
        except Exception:
            pass

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            setor TEXT
        )''')
        db.commit()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS licenca (
            id INTEGER PRIMARY KEY CHECK (id=1),
            tipo TEXT,
            chave_hash TEXT,
            ativado_em TEXT,
            expira_em TEXT,
            status TEXT
        )
        """)
        ja = cursor.execute("SELECT 1 FROM licenca WHERE id=1").fetchone()
        if not ja:
            cursor.execute("INSERT INTO licenca (id, status) VALUES (1, 'EXPIRADA')")
        db.commit()


        # <<< DEPOIS do db.commit() do CREATE TABLE usuarios >>>

        # garantir as novas colunas (para bancos já existentes)
        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN nome TEXT;")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN palavra_chave_hash TEXT;")
        except Exception:
            pass
        db.commit()

        # usuário padrão se não existir (já usando os novos campos)
        u = cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", ("admin",)).fetchone()
        if not u:
            cursor.execute(
                "INSERT INTO usuarios (usuario, senha_hash, setor, nome, palavra_chave_hash) VALUES (?, ?, ?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "ADMINISTRAÇÃO",
                "Administrador", generate_password_hash("admin"))
            )
            db.commit()


        # usuário padrão se não existir
        u = cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", ("admin",)).fetchone()
        if not u:
            cursor.execute(
                "INSERT INTO usuarios (usuario, senha_hash, setor) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "ADMINISTRAÇÃO")
            )
            db.commit()

            # ---- Campos extras e nível ----
        try:    cursor.execute("ALTER TABLE usuarios ADD COLUMN nome TEXT;")
        except: pass
        try:    cursor.execute("ALTER TABLE usuarios ADD COLUMN palavra_chave_hash TEXT;")
        except: pass
        try:    cursor.execute("ALTER TABLE usuarios ADD COLUMN nivel TEXT DEFAULT 'FUNCIONARIO';")
        except: pass
        try:    cursor.execute("ALTER TABLE usuarios ADD COLUMN sess_rev INTEGER DEFAULT 0;")
        except: pass
        # garante que o admin é ADMIN
        cursor.execute("UPDATE usuarios SET nivel='ADMIN' WHERE LOWER(usuario)='admin';")
        db.commit()

        @app.route("/api/admin/force-logout-all", methods=["POST"])
        @exige_login
        @exige_nivel("ADMIN")
        def admin_force_logout_all():
            data = request.get_json() or {}
            # (opcional) exigir senha do admin: if not _checa_senha_admin(data.get("senha_admin") or ""): return jsonify({"error":"Senha de administrador inválida"}), 401
            db = get_db()
            try:
                db.execute("UPDATE usuarios SET sess_rev = COALESCE(sess_rev,0) + 1")
                db.commit()
                return jsonify({"msg":"logout_forcado_de_todos"})
            except Exception as e:
                db.rollback()
                return jsonify({"error": str(e)}), 500
            
        db.commit()

        # Admin padrão com nível
        u = cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", ("admin",)).fetchone()
        if not u:
            cursor.execute("""
                INSERT INTO usuarios (usuario, senha_hash, setor, nome, palavra_chave_hash, nivel)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("admin", generate_password_hash("admin123"), "ADMINISTRAÇÃO",
                "Administrador", generate_password_hash("admin"), "ADMIN"))
            db.commit()

            # Adicione esta tabela na função init_db()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessoes_ativas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    data_criacao TEXT NOT NULL,
                    data_expiracao TEXT NOT NULL,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                )
            ''')

            # --- NOVA TABELA: compras (gastos/entradas de custo) ---
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                produto_id INTEGER,
                servico_id INTEGER,
                descricao TEXT,
                quantidade INTEGER DEFAULT 1,
                custo_unitario REAL NOT NULL,
                total REAL NOT NULL,
                forma_pagamento TEXT,
                data TEXT NOT NULL,
                observacao TEXT,
                fornecedor_id INTEGER,
                categoria_custo TEXT,
                parcela INTEGER DEFAULT 1,
                vencimento TEXT
            )
            ''')

            ## --- CUSTO nos produtos (para valor de estoque por custo) ---
            try:
                cursor.execute("ALTER TABLE produtos ADD COLUMN custo_medio REAL DEFAULT 0")
            except: pass
            try:
                cursor.execute("ALTER TABLE produtos ADD COLUMN ultimo_custo REAL DEFAULT 0")
            except: pass

            db.commit()

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                usuario_nome TEXT,
                acao TEXT,
                tabela TEXT,
                registro_id INTEGER,
                dados_antigos TEXT,
                dados_novos TEXT,
                data TEXT NOT NULL,
                ip TEXT
            )
            ''')
            
            db.commit()
            
        cursor = db.cursor()

        # Tabela fornecedores
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS fornecedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cnpj TEXT,
            contato TEXT,
            data_cadastro TEXT DEFAULT (datetime('now', 'localtime'))
        )
        ''')

        # Tabela categorias_custo
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS categorias_custo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('fixo', 'variável', 'frete', 'taxa', 'embalagem', 'outro'))
        )
        ''')

        # Tabela contas_pagar
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS contas_pagar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id INTEGER,
            fornecedor_id INTEGER,
            descricao TEXT,
            valor_total REAL NOT NULL,
            valor_pago REAL DEFAULT 0,
            parcelas INTEGER DEFAULT 1,
            vencimento TEXT,
            pago_em TEXT,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'pendente' CHECK (status IN ('pendente', 'pago', 'atrasado')),
            observacao TEXT,
            FOREIGN KEY (compra_id) REFERENCES compras(id),
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id)
        )
        ''')

        # Tabela servico_custos
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS servico_custos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            servico_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('mão_de_obra', 'insumo', 'outro')),
            descricao TEXT,
            valor REAL NOT NULL,
            data TEXT NOT NULL,
            FOREIGN KEY (servico_id) REFERENCES servicos(id)
        )
        ''')

        # Tabela lancamentos_caixa
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS lancamentos_caixa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT NOT NULL,
            ref_id INTEGER,
            ref_tipo TEXT,
            data TEXT NOT NULL,
            usuario TEXT,
            observacao TEXT
        )
        ''')

        # Adicionar novas colunas às tabelas existentes
        try:
            cursor.execute("ALTER TABLE compras ADD COLUMN fornecedor_id INTEGER")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE compras ADD COLUMN categoria_custo TEXT")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE compras ADD COLUMN parcela INTEGER DEFAULT 1")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE compras ADD COLUMN vencimento TEXT")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE atendimentos ADD COLUMN desconto_total REAL DEFAULT 0")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE atendimentos ADD COLUMN taxa_cartao REAL DEFAULT 0")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE atendimentos ADD COLUMN frete REAL DEFAULT 0")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE atendimento_itens ADD COLUMN desconto_item REAL DEFAULT 0")
        except:
            pass
            
        try:
            cursor.execute("ALTER TABLE atendimento_itens ADD COLUMN custo_aplicado REAL DEFAULT 0")
        except:
            pass

        # No init_db(), adicione estas colunas à tabela produtos:
        try:
            cursor.execute("ALTER TABLE produtos ADD COLUMN fornecedor_id INTEGER")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE produtos ADD COLUMN fornecedor_cnpj TEXT")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE produtos ADD COLUMN custo_unitario REAL DEFAULT 0")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE compras ADD COLUMN servico_id INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE produtos ADD COLUMN forma_pagamento TEXT")
        except:
            pass

        db.commit()

@app.route('/api/atualizar', methods=['POST'])
@exige_login
def aplicar_atualizacao():
    # Somente ADMIN
    if nivel_atual() != 'ADMIN':
        return jsonify({"error":"sem permissão"}), 403

    fileobj = request.files.get('pacote') or request.files.get('file')
    if not fileobj:
        return jsonify({"error": "arquivo não enviado"}), 400
    raw = fileobj.read()

    def _sha256_bytes(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    db = get_db()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    whitelist = {
        os.path.join(base_dir, 'templates'),
        os.path.join(base_dir, 'static'),
        base_dir  # se precisar tocar api_flask.py e arquivos da raiz do projeto
    }
    def _is_allowed(path):
        ap = os.path.abspath(path)
        return any(ap.startswith(w) for w in whitelist)

    log = []

    # ==== MODO 1: pacote .uniupd (JSON de steps) ====
    is_json = False
    try:
        payload = json.loads(raw.decode('utf-8', errors='strict'))
        is_json = True
    except Exception:
        is_json = False

    if is_json:
        steps = payload.get('steps') or []
        if not isinstance(steps, list):
            return jsonify({"error":"estrutura inválida (steps)"}), 400
        try:
            for i, step in enumerate(steps, start=1):
                t = (step.get('type') or '').lower()

                if t == 'sql':
                    script = step.get('script') or ''
                    if not script.strip():
                        log.append(f"{i}. sql: vazio (ignorado)")
                        continue
                    db.executescript(script)
                    log.append(f"{i}. sql: ok")

                elif t == 'write_file':
                    rel = step.get('path'); content = step.get('content','')
                    if not rel:
                        log.append(f"{i}. write_file: sem path"); continue
                    dest = os.path.abspath(os.path.join(base_dir, rel))
                    if not _is_allowed(dest):
                        log.append(f"{i}. write_file: bloqueado em {rel}"); continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if os.path.exists(dest):
                        with open(dest+'.bak','w',encoding='utf-8') as bk:
                            bk.write(open(dest,'r',encoding='utf-8',errors='ignore').read())
                    with open(dest,'w',encoding='utf-8') as fo:
                        fo.write(content)
                    log.append(f"{i}. write_file: {rel} escrito")

                elif t == 'replace_in_file':
                    rel = step.get('path'); pattern = step.get('pattern'); replace = step.get('replace','')
                    if not (rel and pattern):
                        log.append(f"{i}. replace_in_file: params faltando"); continue
                    dest = os.path.abspath(os.path.join(base_dir, rel))
                    if not _is_allowed(dest) or not os.path.exists(dest):
                        log.append(f"{i}. replace_in_file: bloqueado/arquivo não existe"); continue
                    import re
                    texto = open(dest,'r',encoding='utf-8',errors='ignore').read()
                    novo, qtd = re.subn(pattern, replace, texto, flags=re.DOTALL)
                    if qtd>0:
                        with open(dest+'.bak','w',encoding='utf-8') as bk: bk.write(texto)
                        with open(dest,'w',encoding='utf-8') as fo: fo.write(novo)
                        log.append(f"{i}. replace_in_file: {rel} ({qtd} substituições)")
                    else:
                        log.append(f"{i}. replace_in_file: {rel} (0 substituições)")

                elif t == 'config_update':
                    data = step.get('data') or {}
                    if not isinstance(data, dict):
                        log.append(f"{i}. config_update: dados inválidos"); continue
                    cfg = {}
                    if os.path.exists(CONFIG_PATH):
                        cfg = json.load(open(CONFIG_PATH,'r',encoding='utf-8'))
                    cfg.update(data)
                    json.dump(cfg, open(CONFIG_PATH,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
                    log.append(f"{i}. config_update: ok")

                else:
                    log.append(f"{i}. tipo desconhecido: {t}")

            db.commit()
            return jsonify({"success": True, "log": log})
        except Exception as e:
            db.rollback()
            log.append(f"ERRO: {e}")
            return jsonify({"error":"falha ao aplicar pacote","log":log}), 500

    # ==== MODO 2: pacote ZIP (snapshot completo com sync por hash) ====
    import io, zipfile
    bio = io.BytesIO(raw)
    if not zipfile.is_zipfile(bio):
        return jsonify({"error":"Pacote inválido: nem JSON (.uniupd) nem ZIP"}), 400

    try:
        with zipfile.ZipFile(bio) as zf:
            manifest = {}
            try:
                with zf.open('manifest.json') as mf:
                    manifest = json.load(mf)
            except Exception:
                pass
            delete_extras = bool(manifest.get('delete_extras', False))

            try:
                with zf.open('migrations.sql') as ms:
                    script = ms.read().decode('utf-8', errors='ignore')
                    if script.strip():
                        db.executescript(script)
                        log.append("migrations.sql: ok")
            except KeyError:
                pass

            names = [n for n in zf.namelist()
                     if not n.endswith('/') and n not in ('manifest.json','migrations.sql')]

            for name in names:
                dest = os.path.abspath(os.path.join(base_dir, name))
                if not _is_allowed(dest):
                    log.append(f"bloqueado: {name}")
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                data = zf.read(name)
                new_hash = _sha256_bytes(data)
                old_hash = None
                if os.path.exists(dest):
                    try:
                        old_hash = _sha256_bytes(open(dest,'rb').read())
                    except Exception:
                        pass
                if new_hash != old_hash:
                    if os.path.exists(dest):
                        with open(dest+'.bak','wb') as bk:
                            bk.write(open(dest,'rb').read())
                    with open(dest,'wb') as fo:
                        fo.write(data)
                    log.append(f"updated: {name}")
                else:
                    log.append(f"skip (igual): {name}")

            if delete_extras:
                expected_abs = set(os.path.abspath(os.path.join(base_dir, n)) for n in names)
                for root in (os.path.join(base_dir,'templates'), os.path.join(base_dir,'static')):
                    if not os.path.isdir(root): 
                        continue
                    for dirpath, _, files in os.walk(root):
                        for fn in files:
                            p = os.path.abspath(os.path.join(dirpath, fn))
                            if p.endswith('.bak') or '__pycache__' in p:
                                continue
                            if p not in expected_abs and _is_allowed(p):
                                rel = os.path.relpath(p, base_dir).replace('\\','/')
                                try:
                                    os.remove(p)
                                    log.append(f"deleted: {rel}")
                                except Exception as e:
                                    log.append(f"delete fail: {rel} -> {e}")

        db.commit()
        return jsonify({"success": True, "log": log})
    except Exception as e:
        db.rollback()
        log.append(f"ERRO: {e}")
        return jsonify({"error":"falha ao aplicar pacote","log":log}), 500

@app.route('/api/recuperar-senha/definir', methods=['POST'])
def recuperar_definir():
    data = request.get_json() or {}
    usuario = (data.get('usuario') or '').strip()
    palavra = data.get('palavra_chave') or ''
    s1 = data.get('nova_senha') or ''
    s2 = data.get('confirma') or ''
    if not all([usuario, palavra, s1, s2]):
        return jsonify({"error":"Preencha todos os campos"}), 400
    if s1 != s2 or len(s1) < 4:
        return jsonify({"error":"Senhas não conferem (mín. 4)"}), 400
    db = get_db()
    row = db.execute(
        "SELECT palavra_chave_hash FROM usuarios WHERE usuario=?",
        (usuario,)
    ).fetchone()
    if not row:
        return jsonify({"error":"Usuário não encontrado"}), 404
    if not row['palavra_chave_hash'] or not check_password_hash(row['palavra_chave_hash'], palavra):
        return jsonify({"error":"Palavra-chave incorreta"}), 401
    db.execute(
        "UPDATE usuarios SET senha_hash=? WHERE usuario=?",
        (generate_password_hash(s1), usuario)
    )
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/licenca/upload", methods=["POST"])
@exige_login
def api_licenca_upload():
    if nivel_atual() != "ADMIN" or not _checa_senha_admin(request.form.get("senha_admin") or ""):
        return jsonify({"error": "credenciais_invalidas"}), 401

    if "arquivo" not in request.files:
        return jsonify({"error": "arquivo não enviado"}), 400

    raw = request.files["arquivo"].read()
    try:
        ok, payload = validar_licenca(raw)
        if not ok:
            return jsonify({"error": "licenca_expirada"}), 402
    except Exception as e:
        return jsonify({"error": f"licenca_invalida: {e}"}), 400

    tipo = payload.get("plano")           # ex.: DEMO_7D, MENSAL_30D
    expira = payload.get("expira_em")     # ISO UTC (Z)

    db = get_db()
    db.execute("""
        UPDATE licenca
           SET tipo=?, chave_hash=?, ativado_em=?, expira_em=?, status=?
         WHERE id=1
    """, (
        tipo,
        generate_password_hash(payload.get("lic_id","")),
        payload.get("emitido_em"),
        expira,
        "ATIVA"
    ))
    db.commit()
    return jsonify({"ok": True, "tipo": tipo, "expira_em": expira})

@app.before_request
def br_checa_licenca():
    livres = {
        "login", "logout", "static", "ping",
        "recuperar_validar", "recuperar_definir",
        "api_licenca_get", "api_licenca_upload"
    }
    if request.endpoint in livres or (request.path or "").startswith(("/static/", "/favicon")):
        return
    if not session.get("user_id"):
        return

    st = licenca_status_db()
    if not st.get("ativa"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "licenca_inativa"}), 402
        # EVITA LOOP: só redireciona se NÃO estiver na home
        if request.endpoint != "home" and request.path != "/":
            return redirect(url_for("home"))
        # se já está na home, apenas deixa a requisição seguir (você pode exibir aviso na página)

@app.before_request
def br_bloqueio_usuario_desabilitado():
    livres = {
        "login", "logout", "static", "ping",
        "recuperar_validar", "recuperar_definir",
        "api_licenca_get", "api_licenca_upload"
    }
    ep = (request.endpoint or "")
    if ep in livres or (request.path or "").startswith(("/static/", "/favicon")):
        return

    uid = session.get("user_id")
    if not uid:
        return

    row = get_db().execute(
        "SELECT COALESCE(desabilitado,0) AS desabilitado FROM usuarios WHERE id=?",
        (uid,)
    ).fetchone()

    if row and row["desabilitado"]:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "usuario_desabilitado"}), 403
        return redirect(url_for("login", erro=2))

@app.before_request
def br_checa_revogacao_sessao():
    livres = {"login","logout","static","ping",
              "recuperar_validar","recuperar_definir",
              "api_licenca_get","api_licenca_upload"}
    if (request.endpoint in livres) or (request.path or "").startswith(("/static/","/favicon")):
        return
    uid = session.get("user_id")
    if not uid:
        return
    row = get_db().execute("SELECT COALESCE(sess_rev,0) AS rev FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not row or session.get("sess_rev", -1) != row["rev"]:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error":"sessao_invalidada"}), 401
        return redirect(url_for("login"))

# --- ROTAS PARA COMPRAS ---

@app.route('/api/produtos', methods=['GET', 'POST'])
@exige_login
def produtos():
    db = get_db()
    if request.method == 'GET':
        search = request.args.get('search', '')
        query = 'SELECT * FROM produtos'
        params = []
        if search:
            query += ' WHERE nome LIKE ? OR marca LIKE ? OR tipo LIKE ? OR descricao LIKE ?'
            params = [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%']
        lista_produtos = db.execute(query, params).fetchall()
        return jsonify([dict(p) for p in lista_produtos])

    elif request.method == 'POST':
        # Permissão: FUNCIONARIO, GERENTE ou ADMIN
        if nivel_atual() not in ('FUNCIONARIO', 'GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403

        data = request.get_json()
        db = get_db()
        cursor = db.cursor()

        # Campos obrigatórios
        nome = (data.get('nome') or '').strip()
        marca = (data.get('marca') or '').strip()
        quantidade = int(data.get('quantidade') or 0)
        preco_venda = float(data.get('preco') or 0)
        custo_unitario = float(data.get('custo_unitario') or 0)
        
        if not nome or not marca or quantidade <= 0 or preco_venda <= 0:
            return jsonify({"error": "Campos obrigatórios incompletos"}), 400

        # Verifica se produto já existe
        existe = db.execute(
            'SELECT id FROM produtos WHERE UPPER(nome) = ? AND UPPER(marca) = ?',
            (nome.upper(), marca.upper())
        ).fetchone()
        
        if existe:
            return jsonify({"error": "Produto já cadastrado com este nome e marca"}), 400

        # Cadastro rápido de fornecedor se necessário
        fornecedor_id = data.get('fornecedor_id')
        fornecedor_novo = data.get('fornecedor_novo')
        
        if fornecedor_novo and not fornecedor_id:
            cursor_for = db.cursor()
            cursor_for.execute(
                "INSERT INTO fornecedores (nome, cnpj, contato) VALUES (?, ?, ?)",
                (fornecedor_novo.get('nome', ''), 
                 fornecedor_novo.get('cnpj', ''),
                 fornecedor_novo.get('contato', ''))
            )
            fornecedor_id = cursor_for.lastrowid
            fornecedor_cnpj = fornecedor_novo.get('cnpj', '')
        elif fornecedor_id:
            fornecedor = db.execute(
                "SELECT cnpj FROM fornecedores WHERE id = ?", 
                (fornecedor_id,)
            ).fetchone()
            fornecedor_cnpj = fornecedor['cnpj'] if fornecedor else ''
        else:
            fornecedor_cnpj = ''

        # Insere o produto
        cursor.execute('''
            INSERT INTO produtos (
                tipo, nome, marca, descricao, preco, quantidade, categoria, imagem,
                fornecedor_id, fornecedor_cnpj, custo_unitario, forma_pagamento
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('tipo', ''),
            nome,
            marca,
            data.get('descricao', ''),
            preco_venda,
            quantidade,
            data.get('categoria', ''),
            data.get('imagem', ''),
            fornecedor_id,
            fornecedor_cnpj,
            custo_unitario,
            data.get('forma_pagamento', '')
        ))
        
        produto_id = cursor.lastrowid

        # ===== CORREÇÃO: Só registra compra automática e movimentação se NÃO for cadastro rápido =====
        if not data.get('cadastro_rapido'):
            cursor.execute('''
                INSERT INTO compras (
                    tipo, produto_id, descricao, quantidade, custo_unitario, total,
                    forma_pagamento, data, observacao, fornecedor_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'produto',
                produto_id,
                f'Entrada inicial de {nome} {marca}',
                quantidade,
                custo_unitario,
                custo_unitario * quantidade,
                data.get('forma_pagamento', ''),
                now_br(),
                data.get('observacao', 'Entrada inicial'),
                fornecedor_id
            ))

            cursor.execute('''
                INSERT INTO movimentacao_estoque (produto_id, produto_nome, tipo, quantidade, data, observacao)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                produto_id,
                nome,
                'entrada',
                quantidade,
                now_br(),
                'Cadastro inicial'
            ))

        db.commit()
        return jsonify({"produto_id": produto_id}), 201

@app.route('/api/usuarios', methods=['POST'])
@login_required
@require_nivel('ADMIN')
def criar_usuario():
    data = request.get_json() or {}
    usuario = (data.get('usuario') or '').strip()
    senha = data.get('senha') or ''
    nome = (data.get('nome') or '').strip()
    palavra = data.get('palavra_chave') or ''
    nivel = (data.get('nivel') or 'FUNCIONARIO').upper()
    if nivel not in ('FUNCIONARIO','GERENTE','ADMIN'):
        nivel = 'FUNCIONARIO'
    if not usuario or not senha or not nome or not palavra:
        return jsonify({"error":"Campos obrigatórios"}), 400

    db = get_db()
    ja = db.execute("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)).fetchone()
    if ja: return jsonify({"error":"Login já existe"}), 409

    db.execute("""
        INSERT INTO usuarios (usuario, senha_hash, setor, nome, palavra_chave_hash, nivel)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (usuario, generate_password_hash(senha), '', nome,
          generate_password_hash(palavra), nivel))
    db.commit()
    return jsonify({"success": True})

# ====== ADMIN: listar e gerenciar usuários ======

def _checa_senha_admin(senha_admin:str) -> bool:
    """Confere a senha do usuário logado (que deve ser ADMIN)."""
    if not session.get("user_id"):
        return False
    db = get_db()
    row = db.execute("SELECT senha_hash, UPPER(COALESCE(nivel,'FUNCIONARIO')) AS nivel FROM usuarios WHERE id=?",
                     (session["user_id"],)).fetchone()
    if not row or row["nivel"] != "ADMIN":
        return False
    return check_password_hash(row["senha_hash"], senha_admin or "")

# garante coluna desabilitado no banco (executa 1x sem quebrar)
try:
    with app.app_context():
        get_db().execute("ALTER TABLE usuarios ADD COLUMN desabilitado INTEGER DEFAULT 0;")
        get_db().commit()
except Exception:
    pass

@app.route("/api/admin/usuarios", methods=["GET"])
@exige_login
@exige_nivel("ADMIN")
def admin_listar_usuarios():
    db = get_db()
    rows = db.execute("""
        SELECT id, nome, usuario, UPPER(COALESCE(nivel,'FUNCIONARIO')) AS nivel,
               COALESCE(desabilitado,0) AS desabilitado
        FROM usuarios
        ORDER BY nome COLLATE NOCASE
    """).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/usuarios/<int:uid>/alterar-login", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_alterar_login(uid):
    data = request.get_json() or {}
    novo = (data.get("novo_login") or "").strip()
    senha_admin = data.get("senha_admin") or ""
    if not novo:
        return jsonify({"error":"Novo login obrigatório"}), 400
    if not _checa_senha_admin(senha_admin):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    ja = db.execute("SELECT 1 FROM usuarios WHERE usuario=? AND id<>?", (novo, uid)).fetchone()
    if ja:
        return jsonify({"error":"Login já em uso"}), 409
    db.execute("UPDATE usuarios SET usuario=? WHERE id=?", (novo, uid))
    db.commit()
    return jsonify({"msg":"Login atualizado com sucesso"})

@app.route("/api/admin/usuarios/<int:uid>/alterar-senha", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_alterar_senha(uid):
    data = request.get_json() or {}
    nova = data.get("nova_senha") or ""
    senha_admin = data.get("senha_admin") or ""
    if len(nova) < 4:
        return jsonify({"error":"Senha deve ter ao menos 4 caracteres"}), 400
    if not _checa_senha_admin(senha_admin):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    db.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (generate_password_hash(nova), uid))
    db.commit()
    return jsonify({"msg":"Senha atualizada com sucesso"})

@app.route("/api/admin/usuarios/<int:uid>/alterar-chave", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_alterar_chave(uid):
    data = request.get_json() or {}
    nova = (data.get("nova_palavra_chave") or "").strip()
    senha_admin = data.get("senha_admin") or ""
    if not nova:
        return jsonify({"error":"Palavra-chave obrigatória"}), 400
    if not _checa_senha_admin(senha_admin):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    db.execute("UPDATE usuarios SET palavra_chave_hash=? WHERE id=?",
               (generate_password_hash(nova), uid))
    db.commit()
    return jsonify({"msg":"Palavra-chave atualizada com sucesso"})

@app.route("/api/admin/usuarios/<int:uid>/desabilitar", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_desabilitar(uid):
    data = request.get_json() or {}
    if not _checa_senha_admin(data.get("senha_admin") or ""):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    db.execute("UPDATE usuarios SET desabilitado=1 WHERE id=?", (uid,))
    db.commit()
    return jsonify({"msg":"Usuário desabilitado"})

@app.route("/api/admin/usuarios/<int:uid>/habilitar", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_habilitar(uid):
    data = request.get_json() or {}
    if not _checa_senha_admin(data.get("senha_admin") or ""):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    db.execute("UPDATE usuarios SET desabilitado=0 WHERE id=?", (uid,))
    db.commit()
    return jsonify({"msg":"Usuário habilitado"})

@app.route("/api/admin/usuarios/<int:uid>/excluir", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_excluir(uid):
    data = request.get_json() or {}
    if not _checa_senha_admin(data.get("senha_admin") or ""):
        return jsonify({"error":"Senha de administrador inválida"}), 401

    db = get_db()
    user = db.execute("SELECT usuario FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not user:
        return jsonify({"error":"Usuário não encontrado"}), 404

    # ?? bloqueia exclusão do admin
    if user["usuario"].lower() == "admin":
        return jsonify({"error":"Usuário ADMIN não pode ser excluído"}), 403

    # ?? bloqueia exclusão do próprio usuário logado
    if uid == session.get("user_id"):
        return jsonify({"error":"Não é possível excluir o próprio usuário logado"}), 400

    db.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    db.commit()
    return jsonify({"msg":"Usuário excluído com sucesso"})

@app.route('/api/produtos/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@exige_login
def produto(id):
    db = get_db()

    if request.method == 'GET':
        row = db.execute('SELECT * FROM produtos WHERE id = ?', [id]).fetchone()
        return jsonify(dict(row)) if row else (jsonify({"error": "Produto não encontrado"}), 404)

    elif request.method == 'DELETE':
        if nivel_atual() not in ('GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403

        prod = db.execute('SELECT nome, quantidade FROM produtos WHERE id = ?', [id]).fetchone()
        if not prod:
            return jsonify({"error": "Produto não encontrado"}), 404

        print(f"\n🔍 [DEBUG] Tentando excluir produto ID {id} - {prod['nome']}")

        # ===== BLOCO DE VERIFICAÇÃO (com logs) =====
        # 1. Atendimento itens
        usado_atendimento = db.execute('SELECT 1 FROM atendimento_itens WHERE produto_id = ? LIMIT 1', [id]).fetchone()
        print(f"   - atendimento_itens: {usado_atendimento is not None}")
        if usado_atendimento:
            return jsonify({"error": "Produto vinculado a atendimentos. Exclusão bloqueada."}), 409

        # 2. Compras
        usado_compra = db.execute('SELECT 1 FROM compras WHERE produto_id = ? LIMIT 1', [id]).fetchone()
        print(f"   - compras: {usado_compra is not None}")
        if usado_compra:
            return jsonify({"error": "Produto possui histórico de compras. Exclusão bloqueada."}), 409

        # 3. Movimentações de estoque
        usado_mov = db.execute('SELECT 1 FROM movimentacao_estoque WHERE produto_id = ? LIMIT 1', [id]).fetchone()
        print(f"   - movimentacao_estoque: {usado_mov is not None}")
        if usado_mov:
            return jsonify({"error": "Produto possui movimentações de estoque. Exclusão bloqueada."}), 409

        # 4. Histórico de preços
        usado_historico = db.execute('SELECT 1 FROM historico_precos WHERE produto_id = ? LIMIT 1', [id]).fetchone()
        print(f"   - historico_precos: {usado_historico is not None}")
        if usado_historico:
            return jsonify({"error": "Produto possui histórico de preços. Exclusão bloqueada."}), 409

        # 5. Atendimentos (campo produto_id - se existir)
        try:
            usado_atendimento_direto = db.execute('SELECT 1 FROM atendimentos WHERE produto_id = ? LIMIT 1', [id]).fetchone()
            print(f"   - atendimentos (diretamente): {usado_atendimento_direto is not None}")
            if usado_atendimento_direto:
                return jsonify({"error": "Produto vinculado diretamente a um atendimento. Exclusão bloqueada."}), 409
        except:
            pass

        print("✅ [DEBUG] Nenhum vínculo encontrado. Tentando excluir...")

        # ===== TENTATIVA DE EXCLUSÃO =====
        try:
            # Tenta excluir com foreign keys ligadas
            db.execute('DELETE FROM produtos WHERE id = ?', [id])
            db.commit()
            print(f"🗑️ [DEBUG] Produto {id} excluído com sucesso (FK ON).")
            return jsonify({"success": True})
        except Exception as e:
            print(f"❌ [DEBUG] Erro ao excluir com FK ON: {e}")
            # Se falhar, tenta desligar foreign keys
            db.execute('PRAGMA foreign_keys = OFF')
            db.execute('DELETE FROM produtos WHERE id = ?', [id])
            db.execute('PRAGMA foreign_keys = ON')
            db.commit()
            print(f"⚠️ [DEBUG] Produto {id} excluído com foreign_keys desligadas.")
            return jsonify({"success": True, "warning": "Exclusão forçada devido a constraint não detectada."})

    @app.route('/api/produtos/baixo-estoque', methods=['GET'])
    @exige_login
    def produtos_baixo_estoque():
        db = get_db()
        produtos = db.execute('''
            SELECT * FROM produtos 
            WHERE quantidade <= 0
            ORDER BY nome
        ''').fetchall()
        return jsonify([dict(p) for p in produtos])

    # Serviços
    @app.route('/api/servicos', methods=['GET', 'POST'])
    @exige_login
    def servicos():
        db = get_db()
        if request.method == 'GET':
            search = request.args.get('search', '')
            query = 'SELECT * FROM servicos'
            params = []
            if search:
                query += ' WHERE nome LIKE ? OR descricao LIKE ?'
                params = [f'%{search}%', f'%{search}%']
            servs = db.execute(query, params).fetchall()
            return jsonify([dict(s) for s in servs])

        elif request.method == 'POST':
            # somente GERENTE ou ADMIN podem cadastrar serviço
            if nivel_atual() not in ('FUNCIONARIO','GERENTE', 'ADMIN'):
                return jsonify({"error": "sem permissão"}), 403
            data = request.get_json()
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO servicos (nome, descricao, preco, data_cadastro)
                VALUES (?, ?, ?, ?)
            ''', (data['nome'], data.get('descricao',''), data['preco'], now_br()))
            db.commit()
            return jsonify({"servico_id": cursor.lastrowid}), 201

    @app.route('/api/servicos/<int:id>', methods=['GET', 'PUT', 'DELETE'])
    @exige_login
    def servico(id):
        db = get_db()

        if request.method == 'GET':
            s = db.execute('SELECT * FROM servicos WHERE id = ?', [id]).fetchone()
            return jsonify(dict(s)) if s else (jsonify({"error":"Serviço não encontrado"}), 404)

        elif request.method == 'PUT':
            # somente GERENTE ou ADMIN podem editar serviço
            if nivel_atual() not in ('GERENTE', 'ADMIN'):
                return jsonify({"error": "sem permissão"}), 403
            data = request.get_json()
            db.execute('''
                UPDATE servicos SET
                    nome = COALESCE(?, nome),
                    descricao = COALESCE(?, descricao),
                    preco = COALESCE(?, preco)
                WHERE id = ?
            ''', (data.get('nome'), data.get('descricao'), data.get('preco'), id))
            db.commit()
            return jsonify({"success": True})

        elif request.method == 'DELETE':
            # somente GERENTE ou ADMIN podem excluir serviço
            if nivel_atual() not in ('GERENTE', 'ADMIN'):
                return jsonify({"error": "sem permissão"}), 403
            db.execute('DELETE FROM servicos WHERE id = ?', [id])
            db.commit()
            return jsonify({"success": True})
    
# ===== COMPRAS (gastos) =====

# Crie um decorator para auditoria
def auditar(acao, tabela, registro_id=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resultado = f(*args, **kwargs)
            
            # Registrar auditoria
            db = get_db()
            db.execute('''
                INSERT INTO auditoria (usuario_id, usuario_nome, acao, tabela, registro_id, data, ip)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.get('user_id'),
                session.get('usuario'),
                acao,
                tabela,
                registro_id,
                now_br(),
                request.remote_addr
            ))
            db.commit()
            
            return resultado
        return decorated_function
    return decorator

# Clientes
@app.route('/api/clientes', methods=['GET', 'POST'])
def clientes():
    db = get_db()
    if request.method == 'GET':
        search = request.args.get('search', '')
        nome_exato = request.args.get('nome_exato', '')
        contato_exato = request.args.get('contato_exato', '')
        bairro_exato = request.args.get('bairro_exato', '')
        
        query = 'SELECT * FROM clientes'
        params = []
        conditions = []
        
        # Busca por correspondência parcial (para o modal de pesquisa)
        if search:
            conditions.append('(nome LIKE ? OR contato LIKE ? OR bairro LIKE ?)')
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
        
        # Busca exata para verificação de cliente existente
        if nome_exato:
            conditions.append('nome = ?')
            params.append(nome_exato)
        if contato_exato:
            conditions.append('contato = ?')
            params.append(contato_exato)
        if bairro_exato:
            conditions.append('bairro = ?')
            params.append(bairro_exato)
        
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
            
        clientes = db.execute(query, params).fetchall()
        return jsonify([dict(c) for c in clientes])
    
    elif request.method == 'POST':
        # ?? Permissão: FUNCIONARIO, GERENTE ou ADMIN
        if nivel_atual() not in ('FUNCIONARIO', 'GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403
            
        data = request.get_json()
        cursor = db.cursor()
        
        # Verificar se cliente já existe
        existe = db.execute(
            'SELECT id FROM clientes WHERE nome = ? AND contato = ? AND bairro = ?',
            (data['nome'], data['contato'], data['bairro'])
        ).fetchone()
        
        if existe:
            return jsonify({"error": "Cliente já cadastrado"}), 400
            
        cursor.execute('''
            INSERT INTO clientes (nome, contato, bairro, data_cadastro)
            VALUES (?, ?, ?, ?)
        ''', (
            data['nome'],
            data['contato'],
            data['bairro'],
            data.get('data_cadastro', now_br())
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201

@app.route('/api/clientes/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def cliente(id):
    db = get_db()
    if request.method == 'GET':
        cliente = db.execute('SELECT * FROM clientes WHERE id = ?', [id]).fetchone()
        if cliente:
            return jsonify(dict(cliente))
        return jsonify({"error": "Cliente não encontrado"}), 404
    
    elif request.method == 'PUT':
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            UPDATE clientes SET
                nome = COALESCE(?, nome),
                contato = COALESCE(?, contato),
                bairro = COALESCE(?, bairro)
            WHERE id = ?
        ''', (
            data.get('nome'),
            data.get('contato'),
            data.get('bairro'),
            id
        ))
        db.commit()
        return jsonify({"success": True})
    
    elif request.method == 'DELETE':
        cursor = db.cursor()
        cursor.execute('DELETE FROM clientes WHERE id = ?', [id])
        db.commit()
        return jsonify({"success": True})

# Atendimentos (agora suporta tipo_atendimento)
@app.route('/api/atendimentos', methods=['GET', 'POST'])
def atendimentos():
    db = get_db()
    
    if request.method == 'GET':
        # Parâmetros de filtro
        status = request.args.get('status', 'pendente')
        tipo_atendimento = request.args.get('tipo_atendimento')
        
        # Processa status (pode ser único ou múltiplos separados por vírgula)
        status_list = status.split(',') if ',' in status else [status]
        placeholders = ','.join(['?'] * len(status_list))
        
        # Query base com JOINs
        query = '''
            SELECT a.*, c.nome as cliente_nome, c.contato, c.bairro, p.nome as produto_nome
            FROM atendimentos a
            LEFT JOIN clientes c ON a.cliente_id = c.id
            LEFT JOIN produtos p ON a.produto_id = p.id
            WHERE a.status IN ({})
        '''.format(placeholders)
        
        params = status_list.copy()
        
        # Filtro adicional por tipo de atendimento
        if tipo_atendimento:
            query += ' AND a.tipo_atendimento = ?'
            params.append(tipo_atendimento)
        
        # Verifica e atualiza status pendentes que já deveriam estar em andamento
        mudou = False
        atendimentos = db.execute(query, params).fetchall()
        
        for a in atendimentos:
            if a['status'] == 'pendente' and a['data_inicio']:
                try:
                    data_agendada = parser.isoparse(a['data_inicio'])
                    if data_agendada.tzinfo is None:
                        data_agendada = pytz.timezone("America/Sao_Paulo").localize(data_agendada)
                    agora = datetime.now(pytz.timezone("America/Sao_Paulo"))
                    if agora >= data_agendada:
                        db.execute('UPDATE atendimentos SET status = ? WHERE id = ?', ('andamento', a['id']))
                        mudou = True
                except Exception as e:
                    print("Erro na virada de status:", e)
        
        if mudou:
            db.commit()
            atendimentos = db.execute(query, params).fetchall()
        
        return jsonify([dict(a) for a in atendimentos])

    elif request.method == 'POST':
        data = request.get_json()
        cursor = db.cursor()
        try:
            # === CLIENTE: usa cliente_id se vier, senão cria ===
            if data.get('cliente_id'):
                cliente_id = int(data['cliente_id'])
            else:
                cursor.execute('''
                    INSERT INTO clientes (nome, contato, bairro, data_cadastro)
                    VALUES (?, ?, ?, ?)
                ''', (
                    data['cliente_nome'],
                    data.get('contato', ''),
                    data.get('bairro', ''),
                    now_br()
                ))
                cliente_id = cursor.lastrowid
            # === FIM CLIENTE ===

            status_atendimento = data.get('status', 'concluido')
            data_inicio = data.get('data_inicio', now_br())

            # ... (validação de agendamento futuro) ...

            # Determinação do tipo de atendimento
            tem_itens = 'itens' in data and data['itens'] and len(data['itens']) > 0
            tem_servicos = 'servicos' in data and data['servicos'] and len(data['servicos']) > 0
            if tem_itens and tem_servicos:
                tipo_final = 'produto+serviço'
            elif tem_itens:
                tipo_final = 'produto'
            elif tem_servicos:
                tipo_final = 'serviço'
            else:
                tipo_final = data.get('tipo_servico', 'venda')

            tipo_atendimento = data.get('tipo_atendimento', 'atendimento')

            # ===== NOVO: calcula o total usando Decimal (evita 0,01 a mais) =====
            itens_req = (data.get('itens') or [])
            servicos_req = (data.get('servicos') or [])
            total_decimal = Decimal('0')

            for item in itens_req:
                qtd = Decimal(str(item.get('quantidade', 1)))
                preco = Decimal(str(item.get('preco', 0)))
                total_decimal += (preco * qtd)

            for s in servicos_req:
                qtd = Decimal(str(s.get('quantidade', 1)))
                preco = Decimal(str(s.get('preco', 0)))
                total_decimal += (preco * qtd)

            if not itens_req and not servicos_req:
                total_decimal = Decimal(str(data.get('valor', 0)))

            total_decimal = total_decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            valor_final = float(total_decimal)
            # ===== FIM DO NOVO TRECHO =====

            # Inserção do atendimento principal
            cursor.execute('''
                INSERT INTO atendimentos (
                    cliente_id, atendente, tipo_servico, valor, 
                    forma_pagamento, observacoes, status, data_inicio, data_fim, tipo_atendimento
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                cliente_id,
                data['atendente'],
                tipo_final,
                valor_final,
                data['forma_pagamento'],
                data.get('observacoes', ''),
                status_atendimento,
                data_inicio,
                data.get('data_fim'),
                tipo_atendimento
            ))
            atendimento_id = cursor.lastrowid

            # PASSO B: Grave os serviços detalhadamente
            if 'servicos' in data and data['servicos']:
                for servico in data['servicos']:
                    cursor.execute('''
                        INSERT INTO atendimento_servicos (atendimento_id, servico_id, quantidade)
                        VALUES (?, ?, ?)
                    ''', (
                        atendimento_id,
                        servico['id'],
                        servico.get('quantidade', 1)
                    ))

            # Processamento de itens (movimentação de estoque)
            # Sempre grava os itens na tabela atendimento_itens!
            if 'itens' in data and data['itens']:
                for item in data['itens']:
                    # Buscar custo médio do produto
                    produto = db.execute('SELECT custo_medio FROM produtos WHERE id = ?', [item['id']]).fetchone()
                    custo_aplicado = produto['custo_medio'] if produto else 0
                    
                    cursor.execute('''
                        INSERT INTO atendimento_itens (atendimento_id, produto_id, quantidade, preco, tipo, desconto_item, custo_aplicado)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        atendimento_id,
                        item['id'],
                        item['quantidade'],
                        item.get('preco', 0),
                        'produto',
                        item.get('desconto_item', 0),
                        custo_aplicado
                    ))

            db.commit()
            return jsonify({"id": atendimento_id}), 201
            
        except Exception as e:
            db.rollback()
            import traceback
            print("Erro ao cadastrar atendimento:", traceback.format_exc())
            return jsonify({"error": str(e)}), 400

@app.route('/api/atendimentos/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def atendimento(id):
    db = get_db()
    if request.method == 'GET':
        atendimento = db.execute('''
            SELECT a.*, c.nome as cliente_nome, c.contato, c.bairro
            FROM atendimentos a
            LEFT JOIN clientes c ON a.cliente_id = c.id
            WHERE a.id = ?
        ''', [id]).fetchone()
        if atendimento:
            return jsonify(dict(atendimento))
        return jsonify({"error": "Atendimento não encontrado"}), 404

    elif request.method == 'PUT':
        data = request.get_json()
        cursor = db.cursor()

        # Verifica status anterior para evitar baixa duplicada
        ant = db.execute('SELECT status FROM atendimentos WHERE id = ?', (id,)).fetchone()
        status_ant = ant['status'] if ant else None

        cursor.execute('''
            UPDATE atendimentos SET
                status = COALESCE(?, status),
                data_fim = COALESCE(?, data_fim),
                tempo_servico = COALESCE(?, tempo_servico),
                observacoes = COALESCE(?, observacoes),
                tipo_atendimento = COALESCE(?, tipo_atendimento)
            WHERE id = ?
        ''', (
            data.get('status'),
            data.get('data_fim'),
            data.get('tempo_servico'),
            data.get('observacoes'),
            data.get('tipo_atendimento'),
            id
        ))

        novo_status = data.get('status')

        # Dar baixa no estoque somente se mudou de != concluido para concluido
        if status_ant != 'concluido' and novo_status == 'concluido':
            produtos = db.execute('''
                SELECT produto_id, quantidade FROM atendimento_itens WHERE atendimento_id = ?
            ''', (id,)).fetchall()

            for produto in produtos:
                pid = produto['produto_id']
                quantidade = produto['quantidade']
                if pid and quantidade:
                    cursor.execute('UPDATE produtos SET quantidade = quantidade - ? WHERE id = ?', (quantidade, pid))
                    nome = db.execute('SELECT nome FROM produtos WHERE id = ?', (pid,)).fetchone()
                    produto_nome = nome['nome'] if nome else None
                    cursor.execute('''
                        INSERT INTO movimentacao_estoque (produto_id, produto_nome, tipo, quantidade, data, observacao)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        pid,
                        (produto_nome or ''),  # garante string
                        'saida',
                        int(quantidade),       # garante inteiro
                        now_br(),
                        f'Baixa de estoque (conclusão atendimento {id})'
                    ))
        db.commit()
        return jsonify({"success": True})

    elif request.method == 'DELETE':
        cursor = db.cursor()
        cursor.execute('DELETE FROM atendimentos WHERE id = ?', [id])
        db.commit()
        return jsonify({"success": True})

# Movimentação de Estoque
@app.route('/api/movimentacao-estoque', methods=['GET'])
def movimentacao_estoque():
    db = get_db()
    produto_id = request.args.get('produto_id')
    if produto_id:
        movimentacoes = db.execute('''
            SELECT m.*, COALESCE(m.produto_nome, p.nome) AS produto_nome
            FROM movimentacao_estoque m
            LEFT JOIN produtos p ON m.produto_id = p.id
            WHERE m.produto_id = ?
            ORDER BY m.data DESC
        ''', [produto_id]).fetchall()
    else:
        movimentacoes = db.execute('''
            SELECT m.*, COALESCE(m.produto_nome, p.nome) AS produto_nome
            FROM movimentacao_estoque m
            LEFT JOIN produtos p ON m.produto_id = p.id
            ORDER BY m.data DESC
            LIMIT 100
        ''').fetchall()
    return jsonify([dict(m) for m in movimentacoes])

# Histórico de Preços
@app.route('/api/historico-precos/<int:produto_id>', methods=['GET'])
def historico_precos(produto_id):
    db = get_db()
    historico = db.execute('''
        SELECT h.*, p.nome as produto_nome
        FROM historico_precos h
        JOIN produtos p ON h.produto_id = p.id
        WHERE h.produto_id = ?
        ORDER BY h.data_alteracao DESC
    ''', [produto_id]).fetchall()
    return jsonify([dict(h) for h in historico])

# Categorias
@app.route('/api/categorias', methods=['GET', 'POST'])
def categorias():
    db = get_db()
    if request.method == 'GET':
        categorias = db.execute('SELECT * FROM categorias ORDER BY nome').fetchall()
        resultado = []
        for c in categorias:
            # Conta quantos produtos estão usando este tipo
            tem_produto = db.execute(
                'SELECT COUNT(*) as qtd FROM produtos WHERE UPPER(TRIM(tipo)) = UPPER(TRIM(?))',
                [c['nome']]
            ).fetchone()['qtd'] > 0

            resultado.append({
                'id': c['id'],
                'nome': c['nome'],
                'descricao': c['descricao'],
                'tem_produto': tem_produto
            })
        return jsonify(resultado)
    
    elif request.method == 'POST':
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO categorias (nome, descricao)
            VALUES (?, ?)
        ''', (
            data['nome'],
            data.get('descricao', '')
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201


@app.route('/api/categorias/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def categoria(id):
    db = get_db()
    if request.method == 'GET':
        categoria = db.execute('SELECT * FROM categorias WHERE id = ?', [id]).fetchone()
        if categoria:
            return jsonify(dict(categoria))
        return jsonify({"error": "Categoria não encontrada"}), 404
    
    elif request.method == 'PUT':
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            UPDATE categorias SET
                nome = COALESCE(?, nome),
                descricao = COALESCE(?, descricao)
            WHERE id = ?
        ''', (
            data.get('nome'),
            data.get('descricao'),
            id
        ))
        db.commit()
        return jsonify({"success": True})
    
    elif request.method == 'DELETE':
        cursor = db.cursor()
        cursor.execute('DELETE FROM categorias WHERE id = ?', [id])
        db.commit()
        return jsonify({"success": True})
    
@app.route('/api/relatorios', methods=['GET', 'POST'])
def relatorios():
    periodo = request.args.get('periodo', 'semana')
    inicio = request.args.get('inicio')
    fim = request.args.get('fim')

    db = get_db()
    hoje = datetime.now(pytz.timezone("America/Sao_Paulo")).date()
    data_inicio = hoje
    data_fim = hoje

    if periodo == 'hoje':
        data_inicio = hoje
        data_fim = hoje
    elif periodo == 'semana':
        data_inicio = hoje - timedelta(days=hoje.weekday())
        data_fim = data_inicio + timedelta(days=6)
    elif periodo == 'mes':
        data_inicio = hoje.replace(day=1)
        if hoje.month == 12:
            ultimo_dia = 31
        else:
            proximo_mes = hoje.replace(month=hoje.month+1, day=1)
            ultimo_dia = (proximo_mes - timedelta(days=1)).day
        data_fim = hoje.replace(day=ultimo_dia)
    elif periodo == 'ano':
        data_inicio = hoje.replace(month=1, day=1)
        data_fim = hoje.replace(month=12, day=31)
    elif periodo == 'personalizado' and inicio and fim:
        data_inicio = datetime.strptime(inicio, '%Y-%m-%d').date()
        data_fim = datetime.strptime(fim, '%Y-%m-%d').date()

    # Padroniza para strings YYYY-MM-DD
    di = data_inicio.strftime('%Y-%m-%d')
    df = data_fim.strftime('%Y-%m-%d')

    # Consolidado geral - ATENDIMENTOS
    consolidado = db.execute('''
        SELECT 
            COUNT(*) as total_atendimentos,
            SUM(valor) as total_vendas,
            COUNT(DISTINCT cliente_id) as clientes_atendidos
        FROM atendimentos
        WHERE status = 'concluido'
        AND date(substr(data_inicio,1,10)) BETWEEN ? AND ?
    ''', [di, df]).fetchone()

    # GASTOS - soma do total em compras no período
    gastos_row = db.execute("""
        SELECT COALESCE(SUM(total), 0) as total_gastos
        FROM compras
        WHERE date(substr(data,1,10)) BETWEEN ? AND ?
    """, [di, df]).fetchone()
    total_gastos = float(gastos_row["total_gastos"] or 0)

    # LUCRO - cálculo correto: faturamento menos gastos
    total_vendas = float(consolidado['total_vendas'] or 0)
    lucro = total_vendas - total_gastos

    # === LUCRO DETALHADO: CORRIGIDO - NÃO USA MAIS ultimo_custo ===
    try:
        # Verificar qual coluna de custo existe na tabela produtos
        cursor_col = db.execute("PRAGMA table_info(produtos)").fetchall()
        colunas_produtos = [c[1] for c in cursor_col]
        
        # Escolher a coluna de custo disponível
        if 'custo_medio' in colunas_produtos:
            campo_custo = 'p.custo_medio'
        elif 'custo_unitario' in colunas_produtos:
            campo_custo = 'p.custo_unitario'
        elif 'ultimo_custo' in colunas_produtos:
            campo_custo = 'p.ultimo_custo'
        else:
            campo_custo = '0'  # fallback seguro
        
        # Executar consulta com o campo de custo correto
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
        # Log do erro mas não quebra a requisição
        print(f"Erro no cálculo de lucro detalhado: {e}")
        lucro_detalhado = 0

    # === COMPRAS do período ===
    compras = db.execute("""
        SELECT
            c.id,
            date(substr(c.data,1,10)) AS data,
            c.tipo,
            COALESCE(p.nome, c.descricao) AS descricao,
            f.nome    AS fornecedor_nome,
            f.cnpj    AS fornecedor_cnpj,
            f.contato AS fornecedor_contato,
            c.quantidade,
            c.custo_unitario,
            c.total,
            c.forma_pagamento,
            c.categoria_custo
        FROM compras c
        LEFT JOIN produtos     p ON p.id = c.produto_id
        LEFT JOIN fornecedores f ON f.id = c.fornecedor_id
        WHERE date(substr(c.data,1,10)) BETWEEN ? AND ?
        ORDER BY c.data DESC, c.id DESC
    """, [di, df]).fetchall()

    total_compras = float(total_gastos)  # alias para usar no front

    # Formas de pagamento
    formas_pagamento = db.execute('''
        SELECT 
            forma_pagamento as forma,
            SUM(valor) as valor_total
        FROM atendimentos
        WHERE status = 'concluido'
        AND date(data_inicio) BETWEEN ? AND ?
        GROUP BY forma_pagamento
    ''', [di, df]).fetchall()

    # VENDAS DETALHADAS
    vendas_detalhadas = db.execute('''
        SELECT 
            date(a.data_inicio) as dia,
            a.forma_pagamento,
            p.nome as produto_nome,
            ai.preco as produto_preco,
            SUM(ai.quantidade) as quantidade,
            SUM(ai.quantidade * ai.preco) as valor_total
        FROM atendimento_itens ai
        JOIN produtos p ON ai.produto_id = p.id
        JOIN atendimentos a ON ai.atendimento_id = a.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        AND ai.tipo = 'produto'
        GROUP BY dia, a.forma_pagamento, p.nome, ai.preco
        ORDER BY dia DESC
    ''', [di, df]).fetchall()

    # PRODUTOS VENDIDOS
    produtos_vendidos = db.execute('''
        SELECT 
            p.nome,
            p.preco,
            SUM(ai.quantidade) as quantidade_vendida,
            SUM(ai.quantidade * ai.preco) as valor_total
        FROM atendimento_itens ai
        JOIN produtos p ON ai.produto_id = p.id
        JOIN atendimentos a ON ai.atendimento_id = a.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        AND ai.tipo = 'produto'
        GROUP BY p.nome, p.preco
        ORDER BY quantidade_vendida DESC
        LIMIT 10
    ''', [di, df]).fetchall()

    # PRODUTOS MAIS VENDIDOS
    produtos_mais_vendidos = db.execute('''
        SELECT 
            p.nome,
            SUM(ai.quantidade) as quantidade_vendida
        FROM atendimento_itens ai
        JOIN produtos p ON ai.produto_id = p.id
        JOIN atendimentos a ON ai.atendimento_id = a.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        AND ai.tipo = 'produto'
        GROUP BY p.nome
        ORDER BY quantidade_vendida DESC
        LIMIT 10
    ''', [di, df]).fetchall()

    # SERVIÇOS MAIS PRESTADOS
    servicos_mais_prestados = db.execute('''
        SELECT 
            s.nome as servico,
            COUNT(*) as quantidade,
            SUM(s.preco * ats.quantidade) as valor_total
        FROM atendimento_servicos ats
        JOIN servicos s ON ats.servico_id = s.id
        JOIN atendimentos a ON ats.atendimento_id = a.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        GROUP BY s.nome
        ORDER BY quantidade DESC
        LIMIT 10
    ''', [di, df]).fetchall()

    # DETALHES DOS SERVIÇOS PRESTADOS
    detalhes_servicos_prestados = db.execute('''
        SELECT 
            s.nome AS servico,
            c.nome AS cliente,
            a.id AS atendimento_id,
            ats.quantidade,
            s.preco,
            (s.preco * ats.quantidade) AS valor_total,
            a.data_inicio,
            a.tipo_servico
        FROM atendimento_servicos ats
        JOIN servicos s ON ats.servico_id = s.id
        JOIN atendimentos a ON ats.atendimento_id = a.id
        JOIN clientes c ON a.cliente_id = c.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        ORDER BY a.data_inicio DESC
    ''', [di, df]).fetchall()

    # PRODUTOS BAIXO ESTOQUE
    produtos_baixo_estoque = db.execute('''
        SELECT nome, marca, quantidade
        FROM produtos
        WHERE quantidade <= 5
        ORDER BY quantidade, nome
    ''').fetchall()

    # PRODUTOS ALTO ESTOQUE
    produtos_alto_estoque = db.execute('''
        SELECT nome, marca, quantidade
        FROM produtos
        WHERE quantidade > 20
        ORDER BY quantidade DESC, nome
    ''').fetchall()

    # MOVIMENTAÇÕES DE ESTOQUE
    movimentacoes_estoque = db.execute('''
        SELECT
            m.data,
            COALESCE(m.produto_nome, p.nome) AS produto_nome,
            m.tipo,
            m.quantidade,
            m.observacao
        FROM movimentacao_estoque m
        LEFT JOIN produtos p ON m.produto_id = p.id
        WHERE date(m.data) BETWEEN ? AND ?
        ORDER BY m.data DESC
        LIMIT 100
    ''', [di, df]).fetchall()

    # ATENDENTES
    atendentes = db.execute('''
        SELECT 
            atendente as nome,
            COUNT(*) as atendimentos,
            SUM(valor) as vendas,
            ROUND(SUM(valor)/COUNT(*), 2) as ticket_medio
        FROM atendimentos
        WHERE status = 'concluido'
        AND date(data_inicio) BETWEEN ? AND ?
        GROUP BY atendente
        ORDER BY atendimentos DESC
    ''', [di, df]).fetchall()

    # BAIRROS
    bairros = db.execute('''
        SELECT 
            c.bairro as nome,
            COUNT(a.id) as atendimentos
        FROM atendimentos a
        JOIN clientes c ON a.cliente_id = c.id
        WHERE a.status = 'concluido'
        AND date(a.data_inicio) BETWEEN ? AND ?
        GROUP BY c.bairro
        ORDER BY atendimentos DESC
        LIMIT 10
    ''', [di, df]).fetchall()

    # VENDAS POR DIA/HORA
    if periodo == 'hoje':
        vendas_dia = db.execute("""
            SELECT substr(a.data_inicio,12,2) || ':00' AS hora,
                   SUM(a.valor) AS vendas
            FROM atendimentos a
            WHERE a.status = 'concluido'
              AND date(substr(a.data_inicio,1,10)) = ?
            GROUP BY substr(a.data_inicio,12,2)
            ORDER BY hora
        """, [di]).fetchall()
        
        vendas_dia = [
            {"dia": None, "hora": row["hora"], "vendas": float(row["vendas"] or 0)}
            for row in vendas_dia
        ]
    else:
        vendas_dia = db.execute("""
            SELECT date(substr(a.data_inicio,1,10)) AS dia,
                   SUM(a.valor) AS vendas
            FROM atendimentos a
            WHERE a.status='concluido'
              AND date(substr(a.data_inicio,1,10)) BETWEEN ? AND ?
            GROUP BY date(substr(a.data_inicio,1,10))
            ORDER BY dia
        """, [di, df]).fetchall()
        
        vendas_dia = [
            {"dia": row["dia"], "hora": None, "vendas": float(row["vendas"] or 0)}
            for row in vendas_dia
        ]

    # TICKET MÉDIO
    ticket_medio = 0
    if consolidado['total_atendimentos'] and consolidado['total_atendimentos'] > 0:
        ticket_medio = float(consolidado['total_vendas'] or 0) / consolidado['total_atendimentos']

    # ORÇAMENTOS
    orcamentos_validados = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'orcamento'
        AND status = 'concluido'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    orcamentos_negados = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'orcamento'
        AND status = 'cancelado'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    orcamentos_pendentes = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'orcamento'
        AND status = 'pendente'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    orcamentos_totais = orcamentos_validados + orcamentos_negados + orcamentos_pendentes

    historico_orcamentos = db.execute('''
        SELECT
            date(a.data_inicio) as data,
            c.nome as cliente,
            a.status,
            a.valor,
            a.tipo_servico,
            a.observacoes as observacao
        FROM atendimentos a
        LEFT JOIN clientes c ON a.cliente_id = c.id
        WHERE a.tipo_atendimento = 'orcamento'
        AND date(a.data_inicio) BETWEEN ? AND ?
        ORDER BY a.data_inicio DESC
    ''', [di, df]).fetchall()

    # AGENDAMENTOS
    agendamentos_realizados = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'agendamento'
        AND status = 'concluido'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    agendamentos_cancelados = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'agendamento'
        AND status = 'cancelado'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    agendamentos_pendentes = db.execute('''
        SELECT COUNT(*) as total FROM atendimentos
        WHERE tipo_atendimento = 'agendamento'
        AND status = 'pendente'
        AND date(data_inicio) BETWEEN ? AND ?
    ''', [di, df]).fetchone()['total'] or 0

    agendamentos_totais = agendamentos_realizados + agendamentos_cancelados + agendamentos_pendentes

    historico_agendamentos = db.execute('''
        SELECT
            date(a.data_inicio) as data,
            c.nome as cliente,
            a.status,
            a.valor,
            a.tipo_servico,
            a.observacoes as observacao
        FROM atendimentos a
        LEFT JOIN clientes c ON a.cliente_id = c.id
        WHERE a.tipo_atendimento = 'agendamento'
        AND date(a.data_inicio) BETWEEN ? AND ?
        ORDER BY a.data_inicio DESC
    ''', [di, df]).fetchall()
    
    agendamentos_dia = db.execute('''
        SELECT 
            date(a.data_inicio) as dia,
            COUNT(*) as quantidade
        FROM atendimentos a
        WHERE a.tipo_atendimento = 'agendamento'
        AND date(a.data_inicio) BETWEEN ? AND ?
        GROUP BY date(a.data_inicio)
        ORDER BY dia
    ''', [di, df]).fetchall()

    agendamentos_detalhados = db.execute('''
        SELECT
            a.id,
            date(a.data_inicio) as data,
            c.nome as cliente,
            a.status,
            a.valor,
            a.tipo_servico,
            a.observacoes as observacao
        FROM atendimentos a
        LEFT JOIN clientes c ON a.cliente_id = c.id
        WHERE a.tipo_atendimento = 'agendamento'
        AND date(a.data_inicio) BETWEEN ? AND ?
        ORDER BY a.data_inicio DESC
    ''', [di, df]).fetchall()

    # FORNECEDORES (todos, não filtrados por data)
    fornecedores = db.execute('''
        SELECT id, nome, cnpj, contato
        FROM fornecedores
        ORDER BY nome
    ''').fetchall()

    return jsonify({
        'consolidado': {
            'total_atendimentos': consolidado['total_atendimentos'] or 0,
            'total_vendas': float(consolidado['total_vendas'] or 0),
            'ticket_medio': ticket_medio,
            'produtos_vendidos': sum([p['quantidade_vendida'] for p in produtos_mais_vendidos]) if produtos_mais_vendidos else 0,
            'gastos': total_gastos,
            'lucro': lucro,
            'lucro_detalhado': lucro_detalhado
        },
        'formas_pagamento': [dict(f) for f in formas_pagamento],
        'vendas_detalhadas': [dict(v) for v in vendas_detalhadas],
        'produtos_vendidos': [dict(p) for p in produtos_vendidos],
        'produtos_mais_vendidos': [dict(p) for p in produtos_mais_vendidos],
        'servicos_mais_prestados': [dict(s) for s in servicos_mais_prestados],
        'detalhes_servicos_prestados': [dict(s) for s in detalhes_servicos_prestados],
        'produtos_baixo_estoque': [dict(p) for p in produtos_baixo_estoque],
        'produtos_alto_estoque': [dict(p) for p in produtos_alto_estoque],
        'movimentacoes_estoque': [dict(m) for m in movimentacoes_estoque],
        'atendentes': [dict(a) for a in atendentes],
        'bairros': [dict(b) for b in bairros],
        'vendas_dia': vendas_dia,
        'compras': [dict(c) for c in compras],
        'total_compras': total_compras,
        'fornecedores': [dict(f) for f in fornecedores],
        'orcamentos': {
            'validados': orcamentos_validados,
            'negados': orcamentos_negados,
            'pendentes': orcamentos_pendentes,
            'totais': orcamentos_totais,
        },
        'historico_orcamentos': [dict(o) for o in historico_orcamentos],
        'agendamentos': {
            'realizados': agendamentos_realizados,
            'cancelados': agendamentos_cancelados,
            'pendentes': agendamentos_pendentes,
            'total': agendamentos_totais,
        },
        'historico_agendamentos': [dict(a) for a in historico_agendamentos],
        'agendamentos_dia': [dict(a) for a in agendamentos_dia],
        'agendamentos_detalhados': [dict(a) for a in agendamentos_detalhados],
    })  


@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "GET":
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        else:
            return jsonify({"nome_loja": "", "endereco": "", "cep": "", "cnpj": ""})

    if request.method == "POST":
        data = request.get_json()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return jsonify({"success": True})

def get_config():
    nome_loja = endereco = cep = cnpj = ""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
            nome_loja = cfg.get("nome_loja", "")
            endereco  = cfg.get("endereco", "")
            cep       = cfg.get("cep", "")
            cnpj      = cfg.get("cnpj", "")
    return nome_loja, endereco, cep, cnpj

def get_atendimento_completo(atendimento_id):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Busca o atendimento principal
    c.execute("""
        SELECT a.*, c.nome as cliente_nome
        FROM atendimentos a
        LEFT JOIN clientes c ON a.cliente_id = c.id
        WHERE a.id = ?
    """, (atendimento_id,))
    atendimento = c.fetchone()
    if not atendimento:
        conn.close()
        return None

    # Busca todos os produtos do atendimento
    c.execute("""
        SELECT ai.*, p.nome as produto_nome
        FROM atendimento_itens ai
        LEFT JOIN produtos p ON ai.produto_id = p.id
        WHERE ai.atendimento_id = ?
    """, (atendimento_id,))
    produtos = c.fetchall()

    # Busca todos os serviços do atendimento
    c.execute("""
    SELECT ats.*, s.nome as servico_nome, s.preco as preco
        FROM atendimento_servicos ats
        LEFT JOIN servicos s ON ats.servico_id = s.id
        WHERE ats.atendimento_id = ?
    """, (atendimento_id,))
    servicos = c.fetchall()
    conn.close()
    return {
        "atendimento": atendimento,
        "produtos": produtos,
        "servicos": servicos
    }

@app.route("/api/nota_pdf/<int:atendimento_id>")
def baixar_nota_pdf(atendimento_id):
    # helper para ler colunas de sqlite3.Row com default
    def rget(row, col, default=""):
        try:
            v = row[col]
            return default if v is None else v
        except Exception:
            return default

    dados = get_atendimento_completo(atendimento_id)
    nome_loja, endereco, cep, cnpj = get_config()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFillColorRGB(0, 0, 0)

    # --- Sem dados do atendimento (não use 'venda' aqui) ---
    if not dados or not dados.get("atendimento"):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "NOTA DE COMPRA")
        c.setFont("Helvetica", 12)
        y = height - 90
        c.drawString(50, y, f"Nome da Loja: {nome_loja}"); y -= 16
        c.drawString(50, y, f"Endereço: {endereco}"); y -= 16
        if (cnpj or "").strip(): c.drawString(50, y, f"CNPJ: {cnpj}"); y -= 16
        if (cep or "").strip():  c.drawString(50, y, f"CEP: {cep}");   y -= 16
        c.drawString(50, y, "Atendimento não encontrado.")
        c.save(); buffer.seek(0)
        return send_file(buffer, as_attachment=True,
                         download_name=f"Nota_{atendimento_id}.pdf",
                         mimetype='application/pdf')

    # --- Com dados ---
    venda    = dados["atendimento"]     # sqlite3.Row
    produtos = dados.get("produtos", [])
    servicos = dados.get("servicos", [])

    tipo_atendimento = rget(venda, "tipo_atendimento")
    status           = rget(venda, "status")
    titulo_nota = "ORÇAMENTO" if (tipo_atendimento == "orcamento" and status != "concluido") else "NOTA DE COMPRA"

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, titulo_nota)

    c.setFont("Helvetica", 12)
    y = height - 90
    c.drawString(50, y, f"Nome da Loja: {nome_loja}"); y -= 16
    c.drawString(50, y, f"Endereço: {endereco}"); y -= 16
    if (cnpj or "").strip(): c.drawString(50, y, f"CNPJ: {cnpj}"); y -= 16
    if (cep or "").strip():  c.drawString(50, y, f"CEP: {cep}");   y -= 16

    data_emissao = rget(venda, "data_inicio")
    data_emissao = data_emissao[:16].replace("T"," ") if data_emissao else ""
    c.drawString(50, y, f"Data de Emissão: {data_emissao}"); y -= 16
    c.drawString(50, y, f"Cliente: {rget(venda, 'cliente_nome')}");   y -= 24

    # Tipo / Natureza / Pagamento
    if produtos and servicos:
        tipo, natureza = "VENDA + SERVIÇO", "Venda de mercadoria + Prestação de serviço"
    elif produtos:
        tipo, natureza = "VENDA", "Venda de mercadoria"
    elif servicos:
        tipo, natureza = "SERVIÇO", "Prestação de serviço"
    else:
        tipo, natureza = "ATENDIMENTO", "Outro"

    c.drawString(50, y, f"Tipo: {tipo}"); y -= 16
    c.drawString(50, y, f"Natureza da Operação: {natureza}"); y -= 16
    c.drawString(50, y, f"Forma de Pagamento: {rget(venda, 'forma_pagamento')}"); y -= 24

    # Produtos
    if produtos:
        c.setFont("Helvetica-Bold", 12); c.drawString(50, y, "Produtos:"); y -= 18
        c.setFont("Helvetica", 11)
        c.drawString(55, y, "Nome"); c.drawString(220, y, "Qtd")
        c.drawRightString(340, y, "Unitário"); c.drawRightString(410, y, "Total"); y -= 14
        for p in produtos:
            total = float(p["preco"] or 0) * int(p["quantidade"] or 1)
            c.drawString(55, y, f"{str(p['produto_nome'])[:20]:20s}")
            c.drawRightString(240, y, f"{int(p['quantidade'] or 0):>3}")
            c.drawRightString(340, y, f"R$ {float(p['preco'] or 0):.2f}")
            c.drawRightString(410, y, f"R$ {total:.2f}"); y -= 14
            if y < 100: c.showPage(); y = height - 60
        y -= 10

    # Serviços
    if servicos:
        c.setFont("Helvetica-Bold", 12); c.drawString(50, y, "Serviços:"); y -= 18
        c.setFont("Helvetica", 11)
        c.drawString(55, y, "Nome"); c.drawString(220, y, "Qtd")
        c.drawRightString(340, y, "Unitário"); c.drawRightString(410, y, "Total"); y -= 14
        for s in servicos:
            total = float(s["preco"] or 0) * int(s["quantidade"] or 1)
            c.drawString(55, y, f"{str(s['servico_nome'])[:20]:20s}")
            c.drawRightString(240, y, f"{int(s['quantidade'] or 0):>3}")
            c.drawRightString(340, y, f"R$ {float(s['preco'] or 0):.2f}")
            c.drawRightString(410, y, f"R$ {total:.2f}"); y -= 14
            if y < 100: c.showPage(); y = height - 60
        y -= 10

    # Total e observações
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Valor Total: R$ {float(rget(venda, 'valor', 0) or 0):.2f}"); y -= 18
    c.setFont("Helvetica", 10)
    obs = rget(venda, "observacoes")
    if obs: c.drawString(50, y, f"Obs: {obs}"); y -= 14

    c.save(); buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"Nota de Atendimento_{atendimento_id}.pdf",
                     mimetype='application/pdf')

# Exemplo: endpoint para testar se a API está rodando
@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok", "msg": "API rodando"})

# NOTAS FISCAIS - CRUD BÁSICO

@app.route('/api/notas', methods=['GET', 'POST'])
def notas():
    db = get_db()
    if request.method == 'GET':
        notas = db.execute('SELECT * FROM notas_fiscais ORDER BY data_emissao DESC').fetchall()
        return jsonify([dict(n) for n in notas])
    elif request.method == 'POST':
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO notas_fiscais 
                (numero, serie, data_emissao, natureza_operacao, emitente_nome, emitente_endereco, valor_total)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('numero'),
            data.get('serie'),
            data.get('data_emissao'),
            data.get('natureza_operacao'),
            data.get('emitente_nome'),
            data.get('emitente_endereco'),
            data.get('valor_total')
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201
    

@app.route('/api/notas/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def nota_unica(id):
    db = get_db()
    if request.method == 'GET':
        nota = db.execute('SELECT * FROM notas_fiscais WHERE id = ?', (id,)).fetchone()
        return jsonify(dict(nota)) if nota else ('', 404)
    elif request.method == 'PUT':
        data = request.get_json()
        db.execute('''
            UPDATE notas_fiscais SET
                numero = ?,
                serie = ?,
                data_emissao = ?,
                natureza_operacao = ?,
                emitente_nome = ?,
                emitente_endereco = ?,
                valor_total = ?
            WHERE id = ?
        ''', (
            data.get('numero'),
            data.get('serie'),
            data.get('data_emissao'),
            data.get('natureza_operacao'),
            data.get('emitente_nome'),
            data.get('emitente_endereco'),
            data.get('valor_total'),
            id
        ))
        db.commit()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        db.execute('DELETE FROM notas_fiscais WHERE id = ?', (id,))
        db.commit()
        return jsonify({'success': True})
    
# ============================================================
# COMPRAS — SISTEMA UNIFICADO (PRODUTO / SERVIÇO / USO INTERNO)
# ============================================================

@app.route('/api/compras', methods=['GET'])
@exige_login
def listar_compras():
    db = get_db()
    rows = db.execute("""
        SELECT c.*, 
               p.nome as produto_nome, 
               s.nome as servico_nome,
               f.nome as fornecedor_nome, 
               f.cnpj as fornecedor_cnpj, 
               f.contato as fornecedor_contato
        FROM compras c
        LEFT JOIN produtos p ON p.id = c.produto_id
        LEFT JOIN servicos s ON s.id = c.servico_id
        LEFT JOIN fornecedores f ON f.id = c.fornecedor_id
        ORDER BY datetime(c.data) DESC
    """).fetchall()

    resultado = []
    for r in rows:
        d = dict(r)
        if d.get('tipo') == 'outro':
            d['tipo'] = 'uso_interno'
        resultado.append(d)
    return jsonify(resultado)

@app.route('/api/compras', methods=['POST'])
@exige_login
def criar_compra():
    data = request.get_json() or {}
    db = get_db()
    cursor = db.cursor()

    tipo = (data.get('tipo') or '').strip().lower()
    tipo_db = 'outro' if tipo == 'uso_interno' else tipo

    if tipo_db not in ('produto', 'servico', 'outro'):
        return jsonify({"error": "Tipo inválido. Use: produto, servico, uso_interno"}), 400

    qtd = int(data.get('quantidade') or 0)
    custo = float(data.get('custo_unitario') or 0)
    if qtd <= 0 or custo <= 0:
        return jsonify({"error": "Quantidade e custo unitário devem ser maiores que 0"}), 400

    total = round(qtd * custo, 2)
    produto_id = data.get('produto_id') or None
    servico_id = data.get('servico_id') or None
    fornecedor_id = data.get('fornecedor_id') or None
    descricao = (data.get('descricao') or '').strip()
    data_reg = data.get('data') or now_br()

    if tipo_db == 'produto':
        if not produto_id:
            return jsonify({"error": "Compra do tipo 'produto' exige um produto selecionado"}), 400
        if not descricao:
            p = cursor.execute('SELECT nome FROM produtos WHERE id=?', (produto_id,)).fetchone()
            descricao = p['nome'] if p else ''
    elif tipo_db == 'servico':
        if not servico_id and not descricao:
            return jsonify({"error": "Compra do tipo 'servico' exige um serviço ou descrição"}), 400
        if not descricao and servico_id:
            s = cursor.execute('SELECT nome FROM servicos WHERE id=?', (servico_id,)).fetchone()
            descricao = s['nome'] if s else ''
    else:
        if not descricao:
            return jsonify({"error": "Compra de 'uso interno' exige uma descrição"}), 400
        produto_id = None
        servico_id = None

    # --- VERIFICAÇÃO DE DUPLICATA RECENTE ---
    DUPLICATE_WINDOW_SECONDS = 5
    agora_sp = datetime.now(pytz.timezone("America/Sao_Paulo"))

    if tipo_db == 'produto' and produto_id:
        check_sql = """
            SELECT COUNT(*) FROM compras
            WHERE tipo = 'produto'
              AND produto_id = ?
              AND quantidade = ?
              AND custo_unitario = ?
              AND datetime(data) > datetime(?, '-' || ? || ' seconds')
        """
        check_params = [produto_id, qtd, custo, agora_sp.isoformat(), DUPLICATE_WINDOW_SECONDS]
    elif tipo_db == 'servico' and servico_id:
        check_sql = """
            SELECT COUNT(*) FROM compras
            WHERE tipo = 'servico'
              AND servico_id = ?
              AND quantidade = ?
              AND custo_unitario = ?
              AND datetime(data) > datetime(?, '-' || ? || ' seconds')
        """
        check_params = [servico_id, qtd, custo, agora_sp.isoformat(), DUPLICATE_WINDOW_SECONDS]
    else:
        check_sql = """
            SELECT COUNT(*) FROM compras
            WHERE tipo = 'outro'
              AND descricao = ?
              AND quantidade = ?
              AND custo_unitario = ?
              AND datetime(data) > datetime(?, '-' || ? || ' seconds')
        """
        check_params = [descricao, qtd, custo, agora_sp.isoformat(), DUPLICATE_WINDOW_SECONDS]

    cursor.execute(check_sql, check_params)
    if cursor.fetchone()[0] > 0:
        return jsonify({
            "error": f"Compra idêntica registrada há menos de {DUPLICATE_WINDOW_SECONDS} segundos. Evite duplicatas."
        }), 409

    cursor.execute("""
        INSERT INTO compras (tipo, produto_id, servico_id, descricao, quantidade,
                           custo_unitario, total, forma_pagamento, data, observacao,
                           fornecedor_id, categoria_custo, parcela, vencimento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (tipo_db, produto_id, servico_id, descricao, qtd, custo, total,
          data.get('forma_pagamento', ''), data_reg, data.get('observacao', ''),
          fornecedor_id, data.get('categoria_custo', ''), 
          data.get('parcela', 1), data.get('vencimento', data_reg)))

    compra_id = cursor.lastrowid

    if tipo_db == 'produto' and produto_id:
        prod = cursor.execute(
            'SELECT nome, quantidade, custo_medio FROM produtos WHERE id=?', 
            (produto_id,)
        ).fetchone()

        if prod:
            qtd_atual = prod['quantidade'] or 0
            custo_medio_atual = prod['custo_medio'] or 0
            novo_total_qtd = qtd_atual + qtd

            if novo_total_qtd > 0:
                novo_custo_medio = ((qtd_atual * custo_medio_atual) + (qtd * custo)) / novo_total_qtd
            else:
                novo_custo_medio = custo

            cursor.execute("""
                UPDATE produtos 
                SET quantidade = quantidade + ?,
                    ultimo_custo = ?,
                    custo_medio = ?,
                    custo_unitario = COALESCE(custo_unitario, ?)
                WHERE id = ?
            """, (qtd, custo, novo_custo_medio, custo, produto_id))

            cursor.execute("""
                INSERT INTO movimentacao_estoque 
                (produto_id, produto_nome, tipo, quantidade, data, observacao)
                VALUES (?, ?, 'entrada', ?, ?, ?)
            """, (produto_id, prod['nome'], qtd, data_reg, 
                  f'Entrada via compra #{compra_id}'))

    db.commit()
    return jsonify({"ok": True, "id": compra_id}), 201

@app.route('/api/compras/<int:id>', methods=['PUT'])
@exige_login
def atualizar_compra(id):
    data = request.get_json() or {}
    db = get_db()
    cursor = db.cursor()

    original = cursor.execute('SELECT * FROM compras WHERE id=?', (id,)).fetchone()
    if not original:
        return jsonify({"error": "Compra não encontrada"}), 404

    tipo = (data.get('tipo') or original['tipo']).strip().lower()
    tipo_db = 'outro' if tipo == 'uso_interno' else tipo

    qtd = int(data.get('quantidade')) if data.get('quantidade') is not None else original['quantidade']
    custo = float(data.get('custo_unitario')) if data.get('custo_unitario') is not None else original['custo_unitario']
    total = round(qtd * custo, 2)

    produto_id = data.get('produto_id', original['produto_id'])
    servico_id = data.get('servico_id', original['servico_id'])
    descricao = data.get('descricao', original['descricao'])
    fornecedor_id = data.get('fornecedor_id', original['fornecedor_id'])

    if original['tipo'] == 'produto' and original['produto_id']:
        cursor.execute(
            'UPDATE produtos SET quantidade = quantidade - ? WHERE id = ?',
            (original['quantidade'], original['produto_id'])
        )
        nome_prod = cursor.execute(
            'SELECT nome FROM produtos WHERE id=?', (original['produto_id'],)
        ).fetchone()
        if nome_prod:
            cursor.execute("""
                INSERT INTO movimentacao_estoque 
                (produto_id, produto_nome, tipo, quantidade, data, observacao)
                VALUES (?, ?, 'saida', ?, ?, ?)
            """, (original['produto_id'], nome_prod['nome'], original['quantidade'],
                  now_br(), f'Estorno compra #{id} (edição)'))

    if tipo_db == 'produto' and produto_id:
        if not descricao:
            p = cursor.execute('SELECT nome FROM produtos WHERE id=?', (produto_id,)).fetchone()
            descricao = p['nome'] if p else ''

        prod = cursor.execute(
            'SELECT nome, quantidade, custo_medio FROM produtos WHERE id=?', (produto_id,)
        ).fetchone()

        if prod:
            qtd_atual = (prod['quantidade'] or 0)
            custo_medio_atual = prod['custo_medio'] or 0
            novo_total = qtd_atual + qtd

            if novo_total > 0:
                novo_custo = ((qtd_atual * custo_medio_atual) + (qtd * custo)) / novo_total
            else:
                novo_custo = custo

            cursor.execute("""
                UPDATE produtos 
                SET quantidade = quantidade + ?,
                    ultimo_custo = ?,
                    custo_medio = ?
                WHERE id = ?
            """, (qtd, custo, novo_custo, produto_id))

            cursor.execute("""
                INSERT INTO movimentacao_estoque 
                (produto_id, produto_nome, tipo, quantidade, data, observacao)
                VALUES (?, ?, 'entrada', ?, ?, ?)
            """, (produto_id, prod['nome'], qtd, now_br(), 
                  f'Entrada via compra #{id} (atualizada)'))

    if tipo_db != 'produto':
        produto_id = None
    if tipo_db != 'servico':
        servico_id = None

    cursor.execute("""
        UPDATE compras SET
            tipo = ?, produto_id = ?, servico_id = ?, descricao = ?,
            quantidade = ?, custo_unitario = ?, total = ?,
            forma_pagamento = ?, data = ?, observacao = ?,
            fornecedor_id = ?, categoria_custo = ?
        WHERE id = ?
    """, (tipo_db, produto_id, servico_id, descricao, qtd, custo, total,
          data.get('forma_pagamento', original['forma_pagamento']),
          data.get('data', original['data']),
          data.get('observacao', original['observacao']),
          fornecedor_id,
          data.get('categoria_custo', original['categoria_custo']),
          id))

    db.commit()
    return jsonify({"ok": True})


@app.route('/api/compras/<int:id>', methods=['DELETE'])
@exige_login
def deletar_compra(id):
    db = get_db()
    cursor = db.cursor()

    compra = cursor.execute('SELECT * FROM compras WHERE id=?', (id,)).fetchone()
    if not compra:
        return jsonify({"error": "Compra não encontrada"}), 404

    if compra['tipo'] == 'produto' and compra['produto_id']:
        cursor.execute(
            'UPDATE produtos SET quantidade = quantidade - ? WHERE id = ?',
            (compra['quantidade'], compra['produto_id'])
        )
        nome_prod = cursor.execute(
            'SELECT nome FROM produtos WHERE id=?', (compra['produto_id'],)
        ).fetchone()
        if nome_prod:
            cursor.execute("""
                INSERT INTO movimentacao_estoque 
                (produto_id, produto_nome, tipo, quantidade, data, observacao)
                VALUES (?, ?, 'saida', ?, ?, ?)
            """, (compra['produto_id'], nome_prod['nome'], compra['quantidade'],
                  now_br(), f'Estorno exclusão compra #{id}'))

    cursor.execute('DELETE FROM compras WHERE id=?', (id,))
    db.commit()
    return jsonify({"ok": True})


# Adicione estas novas rotas API
@app.route('/api/fornecedores', methods=['GET', 'POST'])
@exige_login
def fornecedores():
    db = get_db()
    if request.method == 'GET':
        search = request.args.get('search', '')
        query = 'SELECT * FROM fornecedores'
        params = []
        if search:
            query += ' WHERE nome LIKE ? OR cnpj LIKE ?'
            params = [f'%{search}%', f'%{search}%']
        fornecedores = db.execute(query, params).fetchall()
        return jsonify([dict(f) for f in fornecedores])
    
    elif request.method == 'POST':
        if nivel_atual() not in ('GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403
            
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO fornecedores (nome, cnpj, contato)
            VALUES (?, ?, ?)
        ''', (
            data['nome'],
            data.get('cnpj', ''),
            data.get('contato', '')
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201

@app.route('/api/fornecedores/<int:fid>', methods=['GET'])
@exige_login
def fornecedor_por_id(fid):
    db = get_db()
    row = db.execute(
        'SELECT id, nome, cnpj, contato FROM fornecedores WHERE id=?',
        (fid,)
    ).fetchone()
    return (jsonify(dict(row)) if row else ('', 404))

@app.route('/api/fornecedores/<int:id>', methods=['DELETE'])
@exige_login
def excluir_fornecedor(id):
    """Exclui um fornecedor se não houver produtos vinculados"""
    db = get_db()
    
    # Verifica se o fornecedor existe
    fornecedor = db.execute('SELECT nome FROM fornecedores WHERE id = ?', (id,)).fetchone()
    if not fornecedor:
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    
    # Verifica se existem produtos vinculados a este fornecedor
    produtos_vinculados = db.execute(
        'SELECT COUNT(*) as total FROM produtos WHERE fornecedor_id = ?',
        (id,)
    ).fetchone()
    
    if produtos_vinculados['total'] > 0:
        return jsonify({
            "error": f"Não é possível excluir este fornecedor pois existem {produtos_vinculados['total']} produto(s) vinculado(s) a ele."
        }), 409
    
    # Verifica se existem compras vinculadas a este fornecedor
    compras_vinculadas = db.execute(
        'SELECT COUNT(*) as total FROM compras WHERE fornecedor_id = ?',
        (id,)
    ).fetchone()
    
    if compras_vinculadas['total'] > 0:
        return jsonify({
            "error": f"Não é possível excluir este fornecedor pois existem {compras_vinculadas['total']} compra(s) vinculada(s) a ele."
        }), 409
    
    # Se não houver vínculos, exclui o fornecedor
    try:
        db.execute('DELETE FROM fornecedores WHERE id = ?', (id,))
        db.commit()
        
        # Registrar na auditoria se a tabela existir
        try:
            db.execute('''
                INSERT INTO auditoria (usuario_id, usuario_nome, acao, tabela, registro_id, data, ip)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.get('user_id'),
                session.get('usuario'),
                'excluir',
                'fornecedores',
                id,
                now_br(),
                request.remote_addr
            ))
            db.commit()
        except:
            pass  # Tabela de auditoria pode não existir
        
        return jsonify({"success": True, "message": "Fornecedor excluído com sucesso!"})
        
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Erro ao excluir fornecedor: {str(e)}"}), 500

@app.route('/api/categorias-custo', methods=['GET', 'POST'])
@exige_login
def categorias_custo():
    db = get_db()
    if request.method == 'GET':
        categorias = db.execute('SELECT * FROM categorias_custo ORDER BY nome').fetchall()
        return jsonify([dict(c) for c in categorias])
    
    elif request.method == 'POST':
        if nivel_atual() not in ('GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403
            
        data = request.get_json()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO categorias_custo (nome, tipo)
            VALUES (?, ?)
        ''', (
            data['nome'],
            data['tipo']
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201

# Use o decorator nas rotas críticas

@app.route('/api/contas-pagar', methods=['GET', 'POST'])
@exige_login
def contas_pagar():
    db = get_db()
    if request.method == 'GET':
        status = request.args.get('status', 'pendente')
        query = 'SELECT cp.*, f.nome as fornecedor_nome FROM contas_pagar cp LEFT JOIN fornecedores f ON cp.fornecedor_id = f.id'
        params = []
        
        if status != 'todos':
            query += ' WHERE cp.status = ?'
            params = [status]
            
        query += ' ORDER BY cp.vencimento'
        contas = db.execute(query, params).fetchall()
        return jsonify([dict(c) for c in contas])
    
    elif request.method == 'POST':
        if nivel_atual() not in ('GERENTE', 'ADMIN'):
            return jsonify({"error": "sem permissão"}), 403
            
        data = request.get_json()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO contas_pagar (compra_id, fornecedor_id, descricao, valor_total, parcelas, vencimento, forma_pagamento, observacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('compra_id'),
            data.get('fornecedor_id'),
            data.get('descricao'),
            data['valor_total'],
            data.get('parcelas', 1),
            data['vencimento'],
            data.get('forma_pagamento', ''),
            data.get('observacao', '')
        ))
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201
    
@app.route('/api/fluxo-caixa', methods=['GET'])
@exige_login
def fluxo_caixa():
    db = get_db()
    data_inicio = request.args.get('inicio')
    data_fim = request.args.get('fim')
    
    if not data_inicio or not data_fim:
        return jsonify({"error": "Período obrigatório"}), 400
    
    # Entradas (vendas concluídas)
    entradas = db.execute('''
        SELECT date(data_inicio) as data, forma_pagamento, SUM(valor) as total
        FROM atendimentos
        WHERE status = 'concluido' AND date(data_inicio) BETWEEN ? AND ?
        GROUP BY date(data_inicio), forma_pagamento
        ORDER BY data
    ''', [data_inicio, data_fim]).fetchall()
    
    # Saídas (compras)
    saidas = db.execute('''
        SELECT date(data) as data, forma_pagamento, SUM(total) as total
        FROM compras
        WHERE date(data) BETWEEN ? AND ?
        GROUP BY date(data), forma_pagamento
        ORDER BY data
    ''', [data_inicio, data_fim]).fetchall()
    
    # Contas pagas
    contas_pagas = db.execute('''
        SELECT date(pago_em) as data, forma_pagamento, SUM(valor_pago) as total
        FROM contas_pagar
        WHERE status = 'pago' AND date(pago_em) BETWEEN ? AND ?
        GROUP BY date(pago_em), forma_pagamento
        ORDER BY data
    ''', [data_inicio, data_fim]).fetchall()
    
    return jsonify({
        'entradas': [dict(e) for e in entradas],
        'saidas': [dict(s) for s in saidas],
        'contas_pagas': [dict(c) for c in contas_pagas]
    })
    
@app.route('/api/upload-imagem', methods=['POST'])
def upload_imagem():
    if 'imagem' not in request.files:
        return jsonify({"error": "Arquivo não encontrado"}), 400
    
    file = request.files['imagem']
    if file.filename == '':
        return jsonify({"error": "Nome de arquivo vazio"}), 400

    # Cria pasta se não existir
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Valida extensão
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
        return jsonify({"error": "Formato não suportado"}), 400

    # Valida tamanho (exemplo: máximo 2 MB)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({"error": "Arquivo maior que 2MB"}), 400

    filename = 'logo_sistema' + ext
    caminho = os.path.join(UPLOAD_FOLDER, filename)
    file.save(caminho)

    # Salva caminho no config.json
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    config["imagem_logo"] = filename
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return jsonify({"success": True, "imagem": filename})

@app.route('/static/imagens/<filename>')
def imagem_static(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

def get_logo_path():
    if os.path.exists(CONFIG_PATH):
        config = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
        return config.get("imagem_logo", "default_logo.png")
    return "default_logo.png"

@app.route("/api/admin/usuarios/<int:uid>/force-logout", methods=["POST"])
@exige_login
@exige_nivel("ADMIN")
def admin_force_logout(uid):
    data = request.get_json() or {}
    if not _checa_senha_admin(data.get("senha_admin") or ""):
        return jsonify({"error":"Senha de administrador inválida"}), 401
    db = get_db()
    try:
        db.execute("UPDATE usuarios SET sess_rev = COALESCE(sess_rev,0) + 1 WHERE id=?", (uid,))
        db.commit()
        return jsonify({"msg":"logout_forcado"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    


if __name__ == '__main__':
    with app.app_context():
        init_db()   # CRIA AS TABELAS, SE NÃO EXISTIREM!
    app.run(host="0.0.0.0", port=5000, debug=True)