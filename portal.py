"""
Ролевой портал КРИТ: вход, три кабинета (сотрудник снабжения, инженер, поставщик),
номенклатура организации, заявки со статусами, согласование, запросы КП.

Подключение в main.py (три строки):
    import portal
    app.include_router(portal.router)   # API: /api/portal/…
    app.include_router(portal.pages)    # страница кабинетов: /app (файл web/app.html)
Старые маршруты не затрагиваются. База: data/portal.db (создаётся сама).
Демо-учётки: buyer1/buyer123, engineer1/engineer123, supplier1..3/supplier123.
"""
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from nlp_matcher import compare_table, diff_report, find_analogues, load_catalog

DB = Path(__file__).resolve().parent / "data" / "portal.db"
router = APIRouter(prefix="/api/portal", tags=["portal"])

ROLE_NAME = {"buyer": "Сотрудник снабжения", "engineer": "Инженер", "supplier": "Поставщик"}
LINE_LABEL = {"new": "Новая", "proposed": "На согласовании", "rejected": "Замена отклонена",
              "approved": "Согласовано", "rfq": "КП запрошены", "quoted": "КП получены",
              "selected": "Поставщик выбран", "ordered": "Заказано"}
STAGE = {"new": 0, "proposed": 1, "rejected": 1, "approved": 2, "rfq": 3, "quoted": 4, "selected": 5, "ordered": 6}
REQ_LABEL = ["Подбор аналогов", "На согласовании у инженера", "Согласована, можно запрашивать КП",
             "Сбор коммерческих предложений", "Сравнение предложений", "Готова к оформлению заказа", "Закрыта"]

SCHEMA = """
create table if not exists users(id integer primary key, login text unique, pwd_hash text, salt text,
  role text, full_name text, org text, city text);
create table if not exists sessions(token text primary key, user_id integer, created text);
create table if not exists nomenclature(id integer primary key, name text, article text, brand text,
  category text, unit text, note text, active integer default 1, created_by text, created_at text);
create table if not exists requests(id integer primary key, number text, title text, created_by integer, created_at text);
create table if not exists lines(id integer primary key, request_id integer, nom_id integer, name text, article text,
  qty integer, status text default 'new', order_number text default '');
create table if not exists decisions(id integer primary key, line_id integer, analogue_id text, analogue_name text,
  score real, verdict_code text, verdict_text text, comparison_json text, proposed_by text, proposed_at text,
  proposal_comment text, status text default 'pending', decided_by text default '', decided_at text default '',
  decision_comment text default '');
create table if not exists rfqs(id integer primary key, number text, line_id integer, item_name text, qty integer,
  due_date text, comment text, created_by text, created_at text);
create table if not exists rfq_invites(id integer primary key, rfq_id integer, supplier_id integer,
  status text default 'invited', price real, lead_days integer, valid_days integer, comment text default '',
  chosen integer default 0, responded_at text default '');
create table if not exists events(id integer primary key, ts text, request_id integer, actor text, text text);
"""
SEED_USERS = [
    ("buyer1", "buyer123", "buyer", "Иванова Мария Сергеевна", "ООО «Демо-Завод», отдел снабжения", "Москва"),
    ("engineer1", "engineer123", "engineer", "Петров Алексей Николаевич", "ООО «Демо-Завод», служба главного механика", "Москва"),
    ("supplier1", "supplier123", "supplier", "Волга-Комплект", "Волга-Комплект", "Нижний Новгород"),
    ("supplier2", "supplier123", "supplier", "ТД «Подшипник-Центр»", "ТД «Подшипник-Центр»", "Москва"),
    ("supplier3", "supplier123", "supplier", "Сибтехкомплект", "Сибтехкомплект", "Новосибирск"),
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def one(c, q, *a):
    r = c.execute(q, a).fetchone()
    return dict(r) if r else None


def many(c, q, *a):
    return [dict(r) for r in c.execute(q, a).fetchall()]


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()


def log(c, actor, text, request_id=None):
    c.execute("insert into events(ts,request_id,actor,text) values(?,?,?,?)", (now(), request_id, actor, text))


def number(c, prefix, table):
    n = c.execute(f"select count(*) from {table}").fetchone()[0] + 1
    return f"{prefix}-{datetime.now().year}-{n:04d}"


_CATALOG = None


def catalog():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog()
    return _CATALOG


def init():
    with db() as c:
        c.executescript(SCHEMA)
        if not c.execute("select count(*) from users").fetchone()[0]:
            for login, pw, role, name, org, city in SEED_USERS:
                salt = secrets.token_hex(8)
                c.execute("insert into users(login,pwd_hash,salt,role,full_name,org,city) values(?,?,?,?,?,?,?)",
                          (login, _hash(pw, salt), salt, role, name, org, city))
        if not c.execute("select count(*) from nomenclature").fetchone()[0]:
            try:
                imports = [x for x in catalog() if x["role"] == "import"][:10]
            except Exception:
                imports = []
            for x in imports:
                art = x["name"].split()[-1]
                c.execute("insert into nomenclature(name,article,brand,category,unit,note,created_by,created_at) "
                          "values(?,?,?,?,?,?,?,?)", (x["name"], art if re.search(r"\d", art) else "", x["brand"],
                                                      x["category"], "шт", "", "система", now()))


# ------------------------------------------------------------------ вход
def public(u):
    return {"id": u["id"], "login": u["login"], "role": u["role"], "role_name": ROLE_NAME[u["role"]],
            "full_name": u["full_name"], "org": u["org"], "city": u["city"]}


def user_dep(request: Request):
    tok = request.cookies.get("krit_session") or request.headers.get("Authorization", "").removeprefix("Bearer ")
    with db() as c:
        u = one(c, "select u.* from sessions s join users u on u.id=s.user_id where s.token=? and s.created>?",
                tok, (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(timespec="seconds"))
    if not u:
        raise HTTPException(401, "Нужен вход")
    return u


def need(*roles):
    def dep(u=Depends(user_dep)):
        if u["role"] not in roles:
            raise HTTPException(403, "Этот раздел недоступен для вашей роли")
        return u
    return dep


class LoginIn(BaseModel):
    login: str
    password: str
    role: str = ""


@router.post("/login")
def login(b: LoginIn, resp: Response):
    with db() as c:
        u = one(c, "select * from users where login=?", b.login.strip())
        if not u or not secrets.compare_digest(_hash(b.password, u["salt"]), u["pwd_hash"]):
            raise HTTPException(401, "Неверный логин или пароль")
        if b.role and b.role != u["role"]:
            raise HTTPException(403, f"Этот аккаунт относится к кабинету «{ROLE_NAME[u['role']]}»")
        tok = secrets.token_urlsafe(24)
        c.execute("insert into sessions values(?,?,?)", (tok, u["id"], now()))
    resp.set_cookie("krit_session", tok, httponly=True, samesite="lax", max_age=43200)
    return public(u)


@router.post("/logout")
def logout(request: Request, resp: Response):
    with db() as c:
        c.execute("delete from sessions where token=?", (request.cookies.get("krit_session", ""),))
    resp.delete_cookie("krit_session")
    return {"ok": True}


@router.get("/me")
def me(u=Depends(user_dep)):
    return public(u)


@router.get("/summary")
def summary(u=Depends(user_dep)):
    """Счётчики для меню: сколько дел ждёт текущего пользователя."""
    with db() as c:
        if u["role"] == "buyer":
            n = c.execute("select count(*) from lines l join requests r on r.id=l.request_id where r.created_by=? "
                          "and l.status in ('new','rejected','approved','quoted','selected')", (u["id"],)).fetchone()[0]
        elif u["role"] == "engineer":
            n = c.execute("select count(*) from decisions where status='pending'").fetchone()[0]
        else:
            n = c.execute("select count(*) from rfq_invites where supplier_id=? and status='invited'", (u["id"],)).fetchone()[0]
    return {"todo": n}


# --------------------------------------------------------- номенклатура
class NomIn(BaseModel):
    name: str = Field(min_length=2)
    article: str = ""
    brand: str = ""
    category: str = "Подшипник"
    unit: str = "шт"
    note: str = ""


@router.get("/nomenclature")
def nom_list(u=Depends(need("buyer", "engineer"))):
    with db() as c:
        return many(c, "select * from nomenclature where active=1 order by id")


@router.post("/nomenclature")
def nom_add(b: NomIn, u=Depends(need("buyer"))):
    with db() as c:
        cur = c.execute("insert into nomenclature(name,article,brand,category,unit,note,created_by,created_at) "
                        "values(?,?,?,?,?,?,?,?)", (b.name, b.article, b.brand, b.category, b.unit, b.note, u["full_name"], now()))
        return one(c, "select * from nomenclature where id=?", cur.lastrowid)


@router.put("/nomenclature/{nid}")
def nom_edit(nid: int, b: NomIn, u=Depends(need("buyer"))):
    with db() as c:
        if not one(c, "select id from nomenclature where id=? and active=1", nid):
            raise HTTPException(404, "Позиция не найдена")
        c.execute("update nomenclature set name=?,article=?,brand=?,category=?,unit=?,note=? where id=?",
                  (b.name, b.article, b.brand, b.category, b.unit, b.note, nid))
        return one(c, "select * from nomenclature where id=?", nid)


@router.delete("/nomenclature/{nid}")
def nom_del(nid: int, u=Depends(need("buyer"))):
    with db() as c:
        c.execute("update nomenclature set active=0 where id=?", (nid,))
    return {"ok": True}


@router.get("/catalog/imports")
def catalog_imports(q: str = "", u=Depends(need("buyer"))):
    q = q.lower().strip()
    items = [x for x in catalog() if x["role"] == "import" and q in x["name"].lower()]
    return [{"id": x["id"], "name": x["name"], "brand": x["brand"], "category": x["category"]} for x in items[:20]]


@router.post("/nomenclature/from-catalog/{item_id}")
def nom_from_catalog(item_id: str, u=Depends(need("buyer"))):
    x = next((i for i in catalog() if i["id"] == item_id and i["role"] == "import"), None)
    if not x:
        raise HTTPException(404, "Позиция каталога не найдена")
    art = x["name"].split()[-1]
    return nom_add(NomIn(name=x["name"], article=art if re.search(r"\d", art) else "", brand=x["brand"],
                         category=x["category"]), u)


# ----------------------------------------------------------------- заявки
class LineIn(BaseModel):
    nomenclature_id: int
    qty: int = Field(default=1, ge=1)


class ReqIn(BaseModel):
    title: str = ""
    lines: list[LineIn] = Field(min_length=1)


def add_lines(c, rid, lines):
    for l in lines:
        n = one(c, "select * from nomenclature where id=? and active=1", l.nomenclature_id)
        if not n:
            raise HTTPException(400, f"Позиции номенклатуры {l.nomenclature_id} нет")
        c.execute("insert into lines(request_id,nom_id,name,article,qty) values(?,?,?,?,?)",
                  (rid, n["id"], n["name"], n["article"], l.qty))


def line_view(c, l):
    dec = many(c, "select * from decisions where line_id=? order by id desc", l["id"])
    for x in dec:
        x["comparison"] = json.loads(x.pop("comparison_json"))
    rfq = one(c, "select * from rfqs where line_id=? order by id desc limit 1", l["id"])
    if rfq:
        rfq["invites"] = many(c, "select i.id,i.status,i.price,i.lead_days,i.valid_days,i.comment,i.chosen,"
                                 "u.full_name supplier,u.city from rfq_invites i join users u on u.id=i.supplier_id "
                                 "where i.rfq_id=?", rfq["id"])
    return {**l, "status_label": LINE_LABEL[l["status"]], "decisions": dec, "rfq": rfq}


def req_view(c, rid):
    r = one(c, "select r.*,u.full_name author from requests r join users u on u.id=r.created_by where r.id=?", rid)
    if not r:
        raise HTTPException(404, "Заявка не найдена")
    lines = [line_view(c, l) for l in many(c, "select * from lines where request_id=? order by id", rid)]
    stages = [STAGE[l["status"]] for l in lines]
    label = REQ_LABEL[min(stages)] if stages else "Черновик"
    if any(l["status"] == "rejected" for l in lines):
        label = "Есть отклонённые замены, нужен другой аналог"
    r.update(lines=lines, status_label=label, progress=f"{sum(s == 6 for s in stages)}/{len(stages)}",
             events=many(c, "select ts,actor,text from events where request_id=? order by id desc", rid))
    return r


def own_request(c, rid, u):
    r = one(c, "select * from requests where id=?", rid)
    if not r or r["created_by"] != u["id"]:
        raise HTTPException(404, "Заявка не найдена")
    return r


@router.post("/requests")
def req_create(b: ReqIn, u=Depends(need("buyer"))):
    with db() as c:
        num = number(c, "ЗК", "requests")
        cur = c.execute("insert into requests(number,title,created_by,created_at) values(?,?,?,?)",
                        (num, b.title or "Закупка импортных комплектующих", u["id"], now()))
        add_lines(c, cur.lastrowid, b.lines)
        log(c, u["full_name"], f"Создана заявка {num}", cur.lastrowid)
        return req_view(c, cur.lastrowid)


@router.get("/requests")
def req_list(u=Depends(need("buyer", "engineer"))):
    with db() as c:
        where, args = ("where created_by=? ", [u["id"]]) if u["role"] == "buyer" else ("", [])
        ids = [r["id"] for r in many(c, f"select id from requests {where}order by id desc", *args)]
        out = []
        for i in ids:
            v = req_view(c, i)
            out.append({k: v[k] for k in ("id", "number", "title", "created_at", "author", "status_label", "progress")}
                       | {"lines_count": len(v["lines"])})
        return out


@router.get("/requests/{rid}")
def req_get(rid: int, u=Depends(need("buyer", "engineer"))):
    with db() as c:
        if u["role"] == "buyer":
            own_request(c, rid, u)
        return req_view(c, rid)


@router.post("/requests/{rid}/lines")
def req_add_line(rid: int, b: LineIn, u=Depends(need("buyer"))):
    with db() as c:
        own_request(c, rid, u)
        add_lines(c, rid, [b])
        return req_view(c, rid)


# ------------------------------------------------- подбор и согласование
def own_line(c, lid, u):
    l = one(c, "select l.*,r.created_by from lines l join requests r on r.id=l.request_id where l.id=?", lid)
    if not l or l["created_by"] != u["id"]:
        raise HTTPException(404, "Строка не найдена")
    return l


def ranked(name, k):
    feats, res = find_analogues(name, catalog(), top_k=k)
    out = []
    for r in res:
        it = r["item"]
        out.append({"id": it["id"], "name": it["name"], "brand": it["brand"], "standard": it.get("standard", ""),
                    "material": it.get("material", ""), "score": r["score"],
                    "verdict": diff_report(feats, it)[2], "comparison": compare_table(feats, it),
                    "offers": it.get("offers", [])})
    return out


@router.post("/lines/{lid}/candidates")
def candidates(lid: int, u=Depends(need("buyer"))):
    with db() as c:
        l = own_line(c, lid, u)
    return {"line": l["name"], "candidates": ranked(l["name"], 5)}


class ProposeIn(BaseModel):
    analogue_id: str
    comment: str = ""


@router.post("/lines/{lid}/propose")
def propose(lid: int, b: ProposeIn, u=Depends(need("buyer"))):
    with db() as c:
        l = own_line(c, lid, u)
        if l["status"] not in ("new", "rejected"):
            raise HTTPException(400, f"Сейчас строка в статусе «{LINE_LABEL[l['status']]}», замену предлагать нельзя")
        m = next((x for x in ranked(l["name"], 10) if x["id"] == b.analogue_id), None)
        if not m:
            raise HTTPException(400, "Этого аналога нет в результатах подбора")
        if m["verdict"]["code"] in ("no", "unknown"):
            raise HTTPException(400, "Нельзя отправить на согласование: " + m["verdict"]["text"])
        c.execute("insert into decisions(line_id,analogue_id,analogue_name,score,verdict_code,verdict_text,comparison_json,"
                  "proposed_by,proposed_at,proposal_comment) values(?,?,?,?,?,?,?,?,?,?)",
                  (lid, m["id"], m["name"], m["score"], m["verdict"]["code"], m["verdict"]["text"],
                   json.dumps(m["comparison"], ensure_ascii=False), u["full_name"], now(), b.comment))
        c.execute("update lines set status='proposed' where id=?", (lid,))
        log(c, u["full_name"], f"Аналог «{m['name']}» отправлен инженеру (строка «{l['name']}»)", l["request_id"])
        return line_view(c, one(c, "select * from lines where id=?", lid))


@router.get("/engineer/decisions")
def eng_list(status: str = "pending", u=Depends(need("engineer"))):
    cond = "d.status='pending'" if status == "pending" else "d.status!='pending'"
    with db() as c:
        rows = many(c, f"select d.*,l.name original_name,l.qty,r.number request_number,r.id request_id from decisions d "
                       f"join lines l on l.id=d.line_id join requests r on r.id=l.request_id where {cond} order by d.id desc")
    for x in rows:
        x["comparison"] = json.loads(x.pop("comparison_json"))
    return rows


class DecideIn(BaseModel):
    decision: str
    comment: str = ""


@router.post("/decisions/{did}/decide")
def decide(did: int, b: DecideIn, u=Depends(need("engineer"))):
    if b.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision: approved или rejected")
    with db() as c:
        d = one(c, "select d.*,l.request_id from decisions d join lines l on l.id=d.line_id where d.id=?", did)
        if not d or d["status"] != "pending":
            raise HTTPException(400, "Решение уже принято или не найдено")
        if (b.decision == "rejected" or d["verdict_code"] == "check") and len(b.comment.strip()) < 3:
            raise HTTPException(400, "Нужен комментарий: что проверено или почему отклонено")
        c.execute("update decisions set status=?,decided_by=?,decided_at=?,decision_comment=? where id=?",
                  (b.decision, u["full_name"], now(), b.comment.strip(), did))
        c.execute("update lines set status=? where id=?", (b.decision, d["line_id"]))
        word = "согласовал" if b.decision == "approved" else "отклонил"
        log(c, u["full_name"], f"Инженер {word} замену на «{d['analogue_name']}»" + (f": {b.comment.strip()}" if b.comment.strip() else ""),
            d["request_id"])
    return {"ok": True}


# ------------------------------------------------------- запросы КП
@router.get("/suppliers")
def suppliers(u=Depends(need("buyer"))):
    with db() as c:
        return many(c, "select id,full_name name,city from users where role='supplier' order by id")


class RfqIn(BaseModel):
    supplier_ids: list[int] = Field(min_length=1)
    due_days: int = Field(default=3, ge=1, le=30)
    comment: str = ""


@router.post("/lines/{lid}/rfq")
def rfq_create(lid: int, b: RfqIn, u=Depends(need("buyer"))):
    with db() as c:
        l = own_line(c, lid, u)
        if l["status"] != "approved":
            raise HTTPException(400, "Запрос КП возможен только по согласованной замене")
        d = one(c, "select * from decisions where line_id=? and status='approved' order by id desc limit 1", lid)
        sup = many(c, f"select id from users where role='supplier' and id in ({','.join('?' * len(b.supplier_ids))})", *b.supplier_ids)
        if len(sup) != len(set(b.supplier_ids)):
            raise HTTPException(400, "Неизвестный поставщик в списке")
        due = (datetime.now(timezone.utc) + timedelta(days=b.due_days)).date().isoformat()
        num = number(c, "КП", "rfqs")
        cur = c.execute("insert into rfqs(number,line_id,item_name,qty,due_date,comment,created_by,created_at) values(?,?,?,?,?,?,?,?)",
                        (num, lid, d["analogue_name"], l["qty"], due, b.comment, u["full_name"], now()))
        for s in sup:
            c.execute("insert into rfq_invites(rfq_id,supplier_id) values(?,?)", (cur.lastrowid, s["id"]))
        c.execute("update lines set status='rfq' where id=?", (lid,))
        log(c, u["full_name"], f"Запрошены КП {num} у {len(sup)} поставщиков на «{d['analogue_name']}»", l["request_id"])
        return line_view(c, one(c, "select * from lines where id=?", lid))


@router.get("/supplier/rfqs")
def supplier_rfqs(u=Depends(need("supplier"))):
    with db() as c:
        return many(c, "select i.id invite_id,i.status,i.price,i.lead_days,i.valid_days,i.comment,i.responded_at,i.chosen,"
                       "r.number,r.item_name,r.qty,r.due_date,r.comment buyer_comment,r.created_by buyer,r.created_at "
                       "from rfq_invites i join rfqs r on r.id=i.rfq_id where i.supplier_id=? order by i.id desc", u["id"])


class QuoteIn(BaseModel):
    price: float = Field(gt=0)
    lead_days: int = Field(ge=0)
    valid_days: int = Field(default=14, ge=1)
    comment: str = ""


def my_invite(c, iid, u):
    i = one(c, "select i.*,r.line_id,r.number,r.item_name from rfq_invites i join rfqs r on r.id=i.rfq_id where i.id=?", iid)
    if not i or i["supplier_id"] != u["id"]:
        raise HTTPException(404, "Запрос не найден")
    if i["status"] != "invited":
        raise HTTPException(400, "На этот запрос вы уже ответили")
    return i


def touch_quoted(c, line_id):
    c.execute("update lines set status='quoted' where id=? and status='rfq'", (line_id,))


@router.post("/invites/{iid}/quote")
def quote(iid: int, b: QuoteIn, u=Depends(need("supplier"))):
    with db() as c:
        i = my_invite(c, iid, u)
        c.execute("update rfq_invites set status='quoted',price=?,lead_days=?,valid_days=?,comment=?,responded_at=? where id=?",
                  (b.price, b.lead_days, b.valid_days, b.comment, now(), iid))
        touch_quoted(c, i["line_id"])
        rid = one(c, "select request_id from lines where id=?", i["line_id"])["request_id"]
        log(c, u["full_name"], f"Поставщик ответил на {i['number']}: {b.price:.0f} ₽, срок {b.lead_days} дн.", rid)
    return {"ok": True}


@router.post("/invites/{iid}/decline")
def decline(iid: int, b: DecideIn = DecideIn(decision="declined"), u=Depends(need("supplier"))):
    with db() as c:
        i = my_invite(c, iid, u)
        c.execute("update rfq_invites set status='declined',comment=?,responded_at=? where id=?", (b.comment, now(), iid))
        rid = one(c, "select request_id from lines where id=?", i["line_id"])["request_id"]
        log(c, u["full_name"], f"Поставщик отказался от {i['number']}", rid)
    return {"ok": True}


@router.post("/lines/{lid}/demo-quotes")
def demo_quotes(lid: int, u=Depends(need("buyer"))):
    """Для показа без второго браузера: ответы поставщиков из демо-предложений каталога."""
    with db() as c:
        l = own_line(c, lid, u)
        rfq = one(c, "select * from rfqs where line_id=? order by id desc limit 1", lid)
        if l["status"] not in ("rfq", "quoted") or not rfq:
            raise HTTPException(400, "Нет открытого запроса КП")
        base = next((o["price"] for it in catalog() if it["name"] == rfq["item_name"] for o in it.get("offers", [])), 1000)
        rnd = secrets.SystemRandom()
        for i in many(c, "select id from rfq_invites where rfq_id=? and status='invited'", rfq["id"]):
            c.execute("update rfq_invites set status='quoted',price=?,lead_days=?,valid_days=14,comment='демо-ответ',"
                      "responded_at=? where id=?", (round(base * rnd.uniform(.9, 1.15)), rnd.choice([1, 2, 3, 5, 7, 10]), now(), i["id"]))
        touch_quoted(c, lid)
        log(c, "система", f"Демо: поставщики ответили на {rfq['number']}", l["request_id"])
        return line_view(c, one(c, "select * from lines where id=?", lid))


@router.post("/invites/{iid}/select")
def select_supplier(iid: int, u=Depends(need("buyer"))):
    with db() as c:
        i = one(c, "select i.*,r.line_id,r.number from rfq_invites i join rfqs r on r.id=i.rfq_id where i.id=?", iid)
        if not i:
            raise HTTPException(404, "Предложение не найдено")
        l = own_line(c, i["line_id"], u)
        if i["status"] != "quoted" or l["status"] not in ("rfq", "quoted"):
            raise HTTPException(400, "Выбрать можно только полученное предложение")
        c.execute("update rfq_invites set chosen=(id=?) where rfq_id=?", (iid, i["rfq_id"]))
        c.execute("update lines set status='selected' where id=?", (l["id"],))
        sup = one(c, "select full_name from users where id=?", i["supplier_id"])["full_name"]
        log(c, u["full_name"], f"Выбран поставщик {sup} по {i['number']}: {i['price']:.0f} ₽, срок {i['lead_days']} дн.", l["request_id"])
        return line_view(c, one(c, "select * from lines where id=?", l["id"]))


@router.post("/lines/{lid}/order")
def order(lid: int, u=Depends(need("buyer"))):
    with db() as c:
        l = own_line(c, lid, u)
        if l["status"] != "selected":
            raise HTTPException(400, "Сначала выберите поставщика")
        c.execute("update lines set status='ordered',order_number=? where id=?", (f"ЗП-{datetime.now().year}-{lid:04d}", lid))
        log(c, u["full_name"], f"Оформлен заказ по строке «{l['name']}»", l["request_id"])
        return line_view(c, one(c, "select * from lines where id=?", lid))


pages = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


@pages.get("/app")
def app_page():
    return FileResponse(WEB / "app.html")


init()
