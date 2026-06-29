import sqlite3
from datetime import datetime

def criar_banco_dados():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        modelo TEXT NOT NULL,
        marca TEXT NOT NULL,
        quantidade INTEGER NOT NULL DEFAULT 0,
        preco_tela REAL DEFAULT 0,
        preco_capinha REAL DEFAULT 0,
        preco_pelicula REAL DEFAULT 0,
        preco_fone REAL DEFAULT 0,
        preco_carregador REAL DEFAULT 0,
        imagem TEXT,
        data_cadastro DATE NOT NULL
    )
    ''')
    
    conn.commit()
    conn.close()
    print("Banco de dados de estoque criado com sucesso!")

def popular_dados_iniciais():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    
    produtos = [
        ('iPhone 13', 'Apple', 15, 1200.00, 50.00, 30.00, 80.00, 100.00, 'iphone13.jpg', datetime.now().date()),
        ('Galaxy S21', 'Samsung', 12, 1000.00, 45.00, 25.00, 70.00, 90.00, 'galaxys21.jpg', datetime.now().date()),
        ('Redmi Note 10', 'Xiaomi', 20, 600.00, 30.00, 15.00, 50.00, 60.00, 'redminote10.jpg', datetime.now().date()),
        ('Moto G60', 'Motorola', 8, 700.00, 35.00, 20.00, 60.00, 70.00, 'motog60.jpg', datetime.now().date())
    ]
    
    cursor.executemany('''
    INSERT INTO produtos 
    (modelo, marca, quantidade, preco_tela, preco_capinha, preco_pelicula, preco_fone, preco_carregador, imagem, data_cadastro)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', produtos)
    
    conn.commit()
    conn.close()
    print("Dados iniciais de estoque inseridos com sucesso!")

def obter_produtos():
    conn = sqlite3.connect('estoque.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM produtos')
    produtos = cursor.fetchall()
    
    conn.close()
    return produtos

if __name__ == "__main__":
    criar_banco_dados()
    popular_dados_iniciais()