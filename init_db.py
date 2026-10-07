"""Create and seed the sample sales database."""

from pathlib import Path
import sqlite3


DATABASE_PATH = Path(__file__).resolve().parent / "sales.db"


def main() -> None:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS products;

        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL CHECK (price >= 0),
            stock INTEGER NOT NULL CHECK (stock >= 0)
        );

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            customer_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            city TEXT NOT NULL,
            joined_date TEXT NOT NULL
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            order_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
        """
    )
    connection.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Laptop Pro 14", "Electronics", 1599.00, 12),
            (2, "Wireless Headphones", "Electronics", 149.00, 35),
            (3, "Office Chair Ergo", "Furniture", 349.00, 8),
            (4, "Mechanical Keyboard", "Accessories", 89.00, 42),
            (5, "USB-C Dock", "Accessories", 129.00, 20),
        ],
    )
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Andi Wijaya", "andi@example.com", "Jakarta", "2026-01-15"),
            (2, "Siti Rahma", "siti@example.com", "Bandung", "2026-02-03"),
            (3, "Budi Santoso", "budi@example.com", "Surabaya", "2026-02-18"),
            (4, "Maya Putri", "maya@example.com", "Yogyakarta", "2026-03-01"),
        ],
    )
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, 1, 2, 3, "2026-03-02", "completed"),
            (2, 2, 4, 5, "2026-03-05", "completed"),
            (3, 3, 1, 1, "2026-03-08", "completed"),
            (4, 1, 4, 2, "2026-03-12", "completed"),
            (5, 4, 5, 3, "2026-03-15", "pending"),
            (6, 2, 2, 4, "2026-03-18", "completed"),
            (7, 3, 3, 1, "2026-03-20", "cancelled"),
            (8, 4, 4, 6, "2026-03-22", "completed"),
        ],
    )
    connection.commit()
    connection.close()
    print(f"Database berhasil dibuat: {DATABASE_PATH}")


if __name__ == "__main__":
    main()