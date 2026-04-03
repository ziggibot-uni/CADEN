import sqlite3

class CatFoodTracker:
    def __init__(self, db_name):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("CREATE TABLE IF NOT EXISTS cats (id INTEGER PRIMARY KEY, name TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS food (id INTEGER PRIMARY KEY, brand TEXT, flavor TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS consumption (id INTEGER PRIMARY KEY, cat_id INTEGER, food_id INTEGER, date TEXT, FOREIGN KEY (cat_id) REFERENCES cats (id), FOREIGN KEY (food_id) REFERENCES food (id))")
        self.conn.commit()

    def add_cat(self, name):
        self.cursor.execute("INSERT INTO cats (name) VALUES (?)", (name,))
        self.conn.commit()

    def add_food(self, brand, flavor):
        self.cursor.execute("INSERT INTO food (brand, flavor) VALUES (?, ?)", (brand, flavor))
        self.conn.commit()

    def log_consumption(self, cat_name, food_brand, food_flavor, date):
        cat_id = self.get_cat_id(cat_name)
        food_id = self.get_food_id(food_brand, food_flavor)
        self.cursor.execute("INSERT INTO consumption (cat_id, food_id, date) VALUES (?, ?, ?)", (cat_id, food_id, date))
        self.conn.commit()

    def get_cat_id(self, name):
        self.cursor.execute("SELECT id FROM cats WHERE name = ?", (name,))
        return self.cursor.fetchone()[0]

    def get_food_id(self, brand, flavor):
        self.cursor.execute("SELECT id FROM food WHERE brand = ? AND flavor = ?", (brand, flavor))
        return self.cursor.fetchone()[0]

    def get_consumption_history(self, cat_name):
        cat_id = self.get_cat_id(cat_name)
        self.cursor.execute("SELECT f.brand, f.flavor, c.date FROM consumption c JOIN food f ON c.food_id = f.id WHERE c.cat_id = ?", (cat_id,))
        return self.cursor.fetchall()

# Example usage:
tracker = CatFoodTracker('cat_food.db')
tracker.add_cat('Whiskers')
tracker.add_food('Brand1', 'Flavor1')
tracker.log_consumption('Whiskers', 'Brand1', 'Flavor1', '2022-01-01')
print(tracker.get_consumption_history('Whiskers'))