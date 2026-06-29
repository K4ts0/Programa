# UNISYSTEM – Sistema de Gestão de Vendas, Estoque e Relatórios

![UNISYSTEM Logo](https://via.placeholder.com/800x200/10B981/FFFFFF?text=UNISYSTEM)

---

## 📌 Sobre o UNISYSTEM

O **UNISYSTEM** é uma aplicação web completa para gestão de pequenos negócios, desenvolvida com **Flask** (Python) e **SQLite**, com interface moderna e responsiva. O sistema foi projetado para otimizar o controle de **vendas, atendimentos, estoque, compras e relatórios**, oferecendo uma experiência intuitiva tanto para funcionários quanto para administradores.

---

## 🚀 Funcionalidades Principais

### ✅ Módulo de Estoque
- Cadastro, edição e exclusão de **produtos** e **serviços**
- Controle de **quantidade**, **preço de custo e venda**, **categoria** e **fornecedor**
- **Movimentações de estoque** (entradas e saídas) com histórico completo
- **Gráfico de produtos mais vendidos**
- **Alertas** para produtos com baixo estoque

### ✅ Módulo de Atendimentos
- Registro de **atendimentos** (venda de produtos e/ou serviços)
- **Orçamentos** e **agendamentos** com status (pendente, andamento, concluído, cancelado)
- Busca e cadastro rápido de **clientes**
- **Carrinho de compras** com adição de múltiplos itens e serviços
- **Cálculo automático do valor total**
- **Impressão de nota fiscal** (PDF) ao finalizar atendimento

### ✅ Módulo de Compras
- Registro de compras de **produtos** (atualiza estoque automaticamente)
- Compra de **serviços** (custo operacional)
- Compra de **uso interno** (despesas gerais)
- Cadastro e gerenciamento de **fornecedores**
- Histórico completo de compras com filtro por período

### ✅ Módulo de Relatórios
- **Dashboard interativo** com métricas principais:
  - Total de atendimentos
  - Faturamento
  - Ticket médio
  - Produtos vendidos
  - Gastos e lucro
- Gráficos de **vendas por período**, **formas de pagamento**, **produtos mais vendidos**, **serviços mais prestados**, **atendentes**, **bairros** e **agendamentos**
- Filtro por período (hoje, semana, mês, ano, personalizado)
- Exportação de relatórios para análise

### ✅ Administração
- Gerenciamento de **usuários** (criação, edição, desativação, exclusão)
- Controle de **níveis de acesso** (Funcionário, Gerente, Administrador)
- **Recuperação de senha** via palavra‑chave
- **Logout forçado** de usuários
- **Configurações da loja** (nome, endereço, CNPJ, logotipo)
- **Ativação de licença** por arquivo `.lic`

### 🔒 Segurança
- Autenticação com **sessão** e **hash de senha** (Werkzeug)
- **Validação de licença** com criptografia AES‑GCM
- Controle de sessão com **revogação** e **desativação** de usuários
- Bloqueio de rotas por nível de permissão

---

## 🛠️ Tecnologias Utilizadas

| Tecnologia | Finalidade |
|------------|------------|
| **Python 3.11+** | Linguagem principal |
| **Flask** | Framework web |
| **SQLite** | Banco de dados local |
| **Jinja2** | Template engine |
| **HTML5, CSS3, JavaScript** | Front-end (vanilla) |
| **Bootstrap 5** | Estilização responsiva |
| **Chart.js** | Gráficos interativos |
| **ReportLab** | Geração de PDF (notas fiscais) |
| **Cryptography** | Criptografia da licença |
| **dateutil, pytz** | Manipulação de datas e timezone |

--

Home (Dashboard)
Visão geral do sistema, com atalhos para os módulos principais.

Estatísticas rápidas (status do sistema, nível de acesso, hora local).

Acesso aos cards de Atendimentos, Estoque, Relatórios, Usuários, Configurações e Licença.


Atendimentos
Novo Atendimento/Venda/Orçamento/Agendamento:

Preencha os dados do cliente (nome, contato, bairro).

Adicione produtos e/ou serviços ao carrinho.

Escolha forma de pagamento e observações.

Finalize para criar o registro e atualizar o estoque (se venda).

Listas de atendimentos em andamento, orçamentos pendentes e agendamentos.

Botões para finalizar, cancelar e imprimir nota (PDF).


Estoque
Produtos: cadastro, edição, exclusão, pesquisa, gráfico de estoque.

Serviços: cadastro, edição, exclusão.

Compras: registro de entrada de produtos, serviços ou uso interno, com seleção de fornecedor e categoria de custo.

Histórico de compras.


Relatórios
Selecione o período (hoje, semana, mês, ano ou personalizado).

Visualize métricas consolidadas, gráficos e tabelas detalhadas.

Abas separadas para Vendas, Produtos, Serviços, Estoque, Orçamentos, Agendamentos, Atendentes, Bairros, Compras e Fornecedores.

Notas Fiscais: cadastre, edite e exclua notas fiscais manualmente (integração futura).


Administração
Usuários: crie, edite, desabilite, force logout ou exclua usuários (apenas ADMIN).

Configurações: altere nome da loja, endereço, CNPJ, CEP e faça upload do logotipo.

Licença: faça upload do arquivo .lic para ativar funcionalidades (ex: módulo de relatórios).



Desenvolvido por EmMERSON HUGO – UNISYSTEM.
Agradecimentos especiais a todos que contribuíram com ideias e testes




