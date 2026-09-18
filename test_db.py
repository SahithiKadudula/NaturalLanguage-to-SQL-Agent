import sqlite3

conn = sqlite3.connect('Chinook_Sqlite.sqlite')
cursor = conn.execute("Select name from sqlite_master where type = 'table';")
tables = cursor.fetchall()

print("Tables found:")
for t in tables:
    print("-", t[0])

conn.close()
