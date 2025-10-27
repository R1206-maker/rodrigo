import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, date
import pandas as pd
import streamlit as st
import altair as alt

DB_PATH = "data.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def ensure_db():
    with closing(get_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            price REAL NOT NULL CHECK(price >= 0)
        )
        ''')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            qty INTEGER NOT NULL CHECK(qty > 0),
            sold_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )
        ''')
        conn.commit()

@st.cache_data(ttl=10)
def load_products():
    with closing(get_conn()) as conn:
        return pd.read_sql_query("SELECT id, name, price FROM products ORDER BY name", conn)

def add_product(name: str, price: float):
    with closing(get_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute("INSERT OR IGNORE INTO products(name, price) VALUES(?, ?)", (name.strip(), float(price)))
        conn.commit()
    load_products.clear()

def update_product_price(prod_id: int, new_price: float):
    with closing(get_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute("UPDATE products SET price = ? WHERE id = ?", (float(new_price), int(prod_id)))
        conn.commit()
    load_products.clear()

def add_sale(product_id: int, qty: int, sold_at: datetime):
    iso = sold_at.isoformat()
    with closing(get_conn()) as conn, closing(conn.cursor()) as cur:
        cur.execute("INSERT INTO sales(product_id, qty, sold_at) VALUES (?, ?, ?)", (product_id, qty, iso))
        conn.commit()

@st.cache_data(ttl=10)
def load_sales():
    with closing(get_conn()) as conn:
        df = pd.read_sql_query('''
            SELECT s.id, s.product_id, p.name as product, p.price, s.qty, s.sold_at
            FROM sales s
            JOIN products p ON p.id = s.product_id
            ORDER BY s.sold_at DESC, s.id DESC
        ''', conn)
    if not df.empty:
        df["sold_at"] = pd.to_datetime(df["sold_at"])
        df["revenue"] = df["qty"] * df["price"]
    return df

def brl(value: float) -> str:
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"

def section_products():
    st.header("📦 Produtos")
    with st.form("add_product", clear_on_submit=True):
        col1, col2 = st.columns([2,1])
        name = col1.text_input("Nome do produto")
        price = col2.number_input("Preço (R$)", min_value=0.0, step=1.0, format="%.2f")
        submitted = st.form_submit_button("Adicionar")
        if submitted:
            if name.strip() and price >= 0:
                add_product(name, price)
                st.success(f"Produto **{name}** cadastrado com preço {brl(price)}.")
            else:
                st.error("Preencha nome e preço válidos.")

    prods = load_products()
    if prods.empty:
        st.info("Nenhum produto cadastrado ainda.")
    else:
        st.subheader("Lista de produtos")
        st.dataframe(prods.assign(preço=prods["price"].map(brl)).drop(columns=["price"]).rename(columns={"name":"Produto","preço":"Preço (R$)"}), hide_index=True, use_container_width=True)

        with st.expander("Atualizar preços"):
            sel = st.selectbox("Produto", options=prods["name"], index=0)
            chosen = prods[prods["name"]==sel].iloc[0]
            new_price = st.number_input("Novo preço (R$)", min_value=0.0, step=1.0, format="%.2f", value=float(chosen["price"]))
            if st.button("Salvar novo preço"):
                update_product_price(int(chosen["id"]), float(new_price))
                st.success(f"Preço atualizado para {brl(new_price)}")
                st.rerun()

def section_sales():
    st.header("🧾 Registrar venda")
    prods = load_products()
    if prods.empty:
        st.warning("Cadastre produtos primeiro na aba **Produtos**.")
        return

    name = st.selectbox("Produto", options=prods["name"])
    price = float(prods.loc[prods["name"]==name, "price"].iloc[0])
    st.caption(f"Preço atual: {brl(price)}")

    qty = st.number_input("Quantidade", min_value=1, step=1, value=1)
    col1, col2 = st.columns(2)
    d = col1.date_input("Data da venda", value=date.today())
    t = col2.time_input("Hora da venda", value=datetime.now().time())

    if st.button("Adicionar venda"):
        sold_at = datetime.combine(d, t)
        prod_id = int(prods.loc[prods["name"]==name, "id"].iloc[0])
        add_sale(prod_id, int(qty), sold_at)
        st.success(f"Venda adicionada: {qty} × {name} ({brl(price)}) em {sold_at.strftime('%d/%m/%Y %H:%M')}")

    # Mostrar últimas vendas
    sales = load_sales()
    if not sales.empty:
        st.subheader("Vendas recentes")
        show = sales.head(20).copy()
        show["Valor"] = show["revenue"].map(brl)
        show["Quando"] = show["sold_at"].dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(show[["product","qty","Valor","Quando"]].rename(columns={"product":"Produto","qty":"Qtd"}), hide_index=True, use_container_width=True)

def section_dashboard():
    st.header("📊 Dashboard de Vendas")
    now = datetime.now()
    today = now.date()

    sales = load_sales()
    if sales.empty:
        st.info("Sem dados de vendas ainda. Registre algumas vendas para ver os gráficos.")
        return

    # Filtros
    with st.expander("Filtros"):
        cols = st.columns(3)
        start = cols[0].date_input("Início", value=today - timedelta(days=6))
        end = cols[1].date_input("Fim", value=today)
        group_by = cols[2].selectbox("Agrupar por", options=["Dia", "Produto"], index=0)

    # Métricas rápidas
    sales["date"] = sales["sold_at"].dt.date
    sales_today = sales[sales["date"] == today]
    last7 = sales[sales["sold_at"] >= (now - timedelta(days=6))]
    month_start = today.replace(day=1)
    month_df = sales[(sales["date"] >= month_start) & (sales["date"] <= today)]

    kpi1 = sales_today["revenue"].sum()
    kpi2 = last7["revenue"].sum()
    kpi3 = month_df["revenue"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Vendido hoje", brl(kpi1))
    c2.metric("Últimos 7 dias", brl(kpi2))
    c3.metric("No mês (Mês atual)", brl(kpi3))

    # Gráfico do DIA (por produto)
    st.subheader("Hoje")
    if not sales_today.empty:
        day_group = sales_today.groupby("product", as_index=False)["revenue"].sum()
        chart_day = alt.Chart(day_group).mark_bar().encode(
            x=alt.X("product:N", title="Produto"),
            y=alt.Y("revenue:Q", title="Receita (R$)"),
            tooltip=["product","revenue"]
        ).properties(height=300)
        st.altair_chart(chart_day, use_container_width=True)
    else:
        st.caption("Sem vendas hoje.")

    # Gráfico da SEMANA (últimos 7 dias, por dia)
    st.subheader("Semana (últimos 7 dias)")
    if not last7.empty:
        last7 = last7.copy()
        last7["d"] = last7["sold_at"].dt.date
        week_group = last7.groupby("d", as_index=False)["revenue"].sum()
        chart_week = alt.Chart(week_group).mark_line(point=True).encode(
            x=alt.X("d:T", title="Dia"),
            y=alt.Y("revenue:Q", title="Receita (R$)"),
            tooltip=["d","revenue"]
        ).properties(height=300)
        st.altair_chart(chart_week, use_container_width=True)
    else:
        st.caption("Sem vendas na última semana.")

    # Gráfico do MÊS (mês corrente por dia)
    st.subheader("Mês (mês atual)")
    if not month_df.empty:
        month_df = month_df.copy()
        month_df["d"] = month_df["sold_at"].dt.date
        month_group = month_df.groupby("d", as_index=False)["revenue"].sum()
        chart_month = alt.Chart(month_group).mark_area().encode(
            x=alt.X("d:T", title="Dia"),
            y=alt.Y("revenue:Q", title="Receita (R$)"),
            tooltip=["d","revenue"]
        ).properties(height=300)
        st.altair_chart(chart_month, use_container_width=True)
    else:
        st.caption("Sem vendas no mês.")

def main():
    st.set_page_config(page_title="Vendas Simples", page_icon="💸", layout="wide")
    ensure_db()

    st.sidebar.title("Vendas Simples")
    page = st.sidebar.radio("Navegação", ["Cadastrar produtos", "Registrar vendas", "Dashboard"])

    if page == "Cadastrar produtos":
        section_products()
    elif page == "Registrar vendas":
        section_sales()
    else:
        section_dashboard()

    st.sidebar.markdown("---")
    st.sidebar.caption("Feito com ❤️ em Streamlit")

if __name__ == "__main__":
    main()
