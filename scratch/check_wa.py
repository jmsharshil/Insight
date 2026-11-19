import sqlite3
c = sqlite3.connect('db.sqlite3')
cur = c.cursor()
print([r[1] for r in cur.execute('pragma table_info(scheduler_scheduledtask)')])
for r in cur.execute("select * from scheduler_scheduledtask where task_type='whatsapp_send' order by id desc limit 5"):
    print(str(r)[:600])
