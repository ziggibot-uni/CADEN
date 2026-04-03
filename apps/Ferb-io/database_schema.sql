CREATE TABLE cat_food (
    id INT PRIMARY KEY,
    brand VARCHAR(255),
    flavor VARCHAR(255),
    consumption_date DATE
);
CREATE TABLE cat_info (
    id INT PRIMARY KEY,
    name VARCHAR(255),
    owner VARCHAR(255)
);
CREATE TABLE consumption (
    id INT PRIMARY KEY,
    cat_id INT,
    food_id INT,
    consumption_date DATE,
    FOREIGN KEY (cat_id) REFERENCES cat_info(id),
    FOREIGN KEY (food_id) REFERENCES cat_food(id)
);