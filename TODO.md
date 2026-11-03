## Высокий приоритет

### 5. Слишком слабая типизация данных

Файл:

`kover/typings.py:16`

```python
DictT = dict[str, Any]
```

`DictT` фактически означает «любой словарь». Это снижает пользу строгой типизации практически во всех слоях:

- команды MongoDB;
- ответы сервера;
- документы;
- параметры операций;
- ошибки;
- BSON-структуры.

Рекомендации:

1. Разделить типы:
   - `MongoDocument`;
   - `MongoCommand`;
   - `MongoReply`;
   - `JsonValue`;
   - `BsonValue`.

2. Использовать рекурсивные type aliases:

```python
type JsonValue = (
    None | bool | int | float | str |
    list["JsonValue"] |
    dict[str, "JsonValue"]
)
```

3. Для команд и ответов применять `TypedDict`.

Полностью отказаться от `Any` не получится, но его следует изолировать на границе wire protocol.

---

### 7. `ConnectionPool` реализует только lazy pool, но не полноценный lifecycle

Файл:

`kover/network/pool.py`

Проблемы:

- нет явного idle timeout;
- нет max lifetime соединения;
- нет health check перед выдачей соединения;
- нет автоматического восстановления топологии;
- первичный узел определяется только при создании pool;
- при смене primary pool не перестраивается;
- отсутствует server selection timeout;
- нет socket/connect timeout;
- нет wait queue timeout.

Для MongoDB-драйвера это существенные архитектурные ограничения.

Особенно проблемно:

```python
host, port = parsed.node_list[0]
```

Используется только первый seed. Replica set discovery фактически не реализован полноценно.

Следующий этап — выделить `TopologyMonitor`/`ServerSelector`, который будет хранить состояние узлов и выбирать подходящий сервер.

---

### 10. Обработка ошибок в `WireHelper` содержит логическую проблему

Файл:

`kover/network/wirehelper.py:223-239`

Сначала проверяется наличие `"code"`:

```python
if "code" in reply:
    ...
```

А уже после этого проверяется `TransientTransactionError`.

Это означает, что ветка:

```python
if self._has_error_label("TransientTransactionError", reply):
```

для большинства обычных ответов с `code` недостижима.

Кроме того, внутри неё вызывается:

```python
get_exception_type(reply["codeName"])
```

Но `get_exception_type()` ожидает числовой код, а не имя ошибки. В результате соответствующий exception type, скорее всего, не будет найден.

Нужно:

- сначала извлекать numeric code;
- отдельно учитывать error labels;
- хранить labels в `OperationFailure`;
- маппить `code`, а не `codeName`;
- реализовать специализированные свойства:
  - `is_retryable`;
  - `is_transient_transaction_error`;
  - `is_unknown_commit_result`.

---

## Средний приоритет

### 11. Генератор MongoDB-схемы слишком хрупко модифицирует схему Pydantic

Файл:

`kover/schema/generator.py`

Генератор активно мутирует словари, полученные от Pydantic:

```python
field.pop(...)
field["bsonType"] = ...
del field["title"]
```

Проблемы:

- неочевидно, где словарь является локальной копией, а где может быть повторно использован;
- кэширование `$ref` хранит мутированные объекты;
- порядок обработки влияет на результат;
- часть unsupported keywords просто удаляется;
- возможна потеря семантики ограничений.

Например:

```python
for kw in ("transform", "format", "default"):
    if kw in field:
        del field[kw]
```

Безопасно удалять `format` не всегда корректно: часть форматов можно преобразовывать в MongoDB-ограничения, а часть нужно явно предупреждать как неподдерживаемую.

Лучше сделать отдельный immutable transformation pipeline:

```text
Pydantic schema
  -> resolve refs
  -> normalize JSON Schema
  -> map JSON types to BSON
  -> validate MongoDB compatibility
  -> emit schema
```

Каждый этап должен возвращать новую структуру, а не мутировать входную.

---

### 12. Удаление неподдерживаемых ограничений происходит молча

Генератор удаляет:

- `format`;
- `default`;
- `transform`;
- потенциально другие ключи, которые MongoDB не понимает.

Пользователь не получает предупреждения, что часть валидации потеряна.

Например, `EmailStr` может превратиться просто в `string`, а `format: email` исчезнет.

Рекомендуется:

- иметь режим `strict=True`;
- выбрасывать `SchemaGenerationException` при неподдерживаемых конструкциях;
- либо выдавать `warnings.warn`;
- вести отчёт о потерянных ограничениях.

Например:

```python
SchemaGenerationReport(
    dropped_keywords={"format"},
    approximated_keywords={"exclusiveMinimum"},
)
```

---

### 13. `$id` хранится как `PrivateAttr`, что усложняет модель документа

В `Document`:

```python
_id: ObjectId | None = PrivateAttr(default=None)
```

Плюсы — `_id` не попадает в пользовательскую схему модели. Но есть архитектурные минусы:

- `_id` не участвует в обычной Pydantic-валидации;
- `set_object_id()` принимает любой объект, несмотря на аннотацию;
- копирование модели может вести себя неожиданно;
- `model_copy()` и сериализация требуют специальных правил;
- невозможно удобно использовать `_id` как часть модели без дополнительной логики.

Стоит рассмотреть отдельную базовую модель с явным полем `_id`, но исключать его из схемы вложенных документов и пользовательского API через кастомную генерацию.

Если оставлять `PrivateAttr`, нужно хотя бы:

- валидировать ID в `set_object_id`;
- запретить смену `_id` после установки либо явно документировать это;
- добавить тесты для `model_copy`, deepcopy и повторной сериализации.

---

### 14. Несогласованная политика `extra`

`Document` использует:

```python
extra="forbid"
```

`ModelMixin` использует:

```python
extra="allow"
```

Это две разные философии моделей в одном проекте:

- доменные документы строго валидируются;
- служебные модели молча принимают неизвестные поля.

Для серверных reply это иногда оправдано, но тогда лучше использовать отдельную базу:

```python
class ServerReplyModel(BaseModel):
    model_config = ConfigDict(extra="allow")
```

А не общий `ModelMixin`.

Иначе новые поля от MongoDB могут незаметно теряться или попадать в сериализацию обратно.

---

### 15. `Collection.__getattr__()` и `Database.__getattr__()` скрывают ошибки

Пример:

```python
def __getattr__(self, name: str) -> Collection:
    return self.database.get_collection(...)
```

И аналогично для database.

Проблемы:

- опечатка в обычном атрибуте превращается в имя MongoDB-коллекции;
- IDE и статический анализ хуже понимают API;
- невозможно отличить отсутствие атрибута от динамического доступа;
- внутренние ошибки `AttributeError` могут превращаться в неожиданные обращения к БД.

Лучше:

- оставить динамический доступ только как явно документированный convenience API;
- добавить `db.collection("name")`;
- в `__getattr__` ограничить имена или корректно обрабатывать private attributes;
- использовать typed namespace proxy.

---

### 16. `Collection.create_if_not_exists()` имеет race condition

Файл:

`kover/collection.py:55-64`

Сначала выполняется `list_collections()`, затем `create_collection()`.

Два процесса могут одновременно увидеть отсутствие коллекции и оба попытаться создать её. Один получит `NamespaceExists`.

Нужно ловить конкретную MongoDB-ошибку `NamespaceExists` и затем вернуть существующую коллекцию.

Вообще паттерн должен быть:

```text
try create
except NamespaceExists:
    return existing
```

а не check-then-create.

---

### 17. `BulkWriteBuilder` допускает изменение уже собранной команды

`build()` возвращает ссылки на внутренние структуры:

```python
"ops": self._operations,
"cursor": self.cursor,
"let": self.let,
```

Пользователь может изменить результат `build()` и тем самым изменить внутреннее состояние builder.

Также `cursor_batch_size or 101` превращает `0` в `101`, хотя `0` может быть валидным значением MongoDB.

Следует:

- возвращать копию или immutable representation;
- валидировать диапазоны;
- использовать `if cursor_batch_size is not None`;
- запретить `build()` после финализации либо сделать builder immutable.

---

### 18. Дублирование API сериализации

В проекте есть несколько вариантов:

- `Document.to_dict()`;
- `ModelMixin.to_dict()`;
- `pydantic.model_dump()`;
- `maybe_to_dict()`;
- ручная сериализация в операциях.

Это приводит к разной политике:

- `Document.to_dict()` не исключает `None`;
- `ModelMixin.to_dict()` использует `exclude_none=True`;
- оба используют alias, но ведут себя по-разному;
- часть моделей сериализуется через `to_dict()`, часть через `model_dump()`.

Нужно определить единый контракт:

```python
to_mongo_document()
from_mongo_document()
```

И использовать его в collection, GridFS, operations и bulk write.

---

## Низкий приоритет, но стоит исправить

### 19. Удаление функций из `helpers.py` происходит отдельно и незаметно

Текущий рабочий diff удаляет из `/home/maksim/code/python/kover/kover/helpers.py`:

- `isinstance_ex`;
- `is_origin_ex`.

Это незакоммиченные изменения относительно текущего `HEAD`. Если они больше не используются — нормально, но стоит:

- проверить публичные импорты;
- добавить changelog;
- убедиться, что это не breaking change;
- удалить их отдельным осмысленным коммитом, а не смешивать с другими изменениями.

---

### 20. Отсутствуют timeout-параметры на уровне публичного API

Сейчас не видно полноценных настроек:

- connect timeout;
- socket timeout;
- server selection timeout;
- wait queue timeout;
- transaction timeout.

Любой сетевой вызов потенциально может ждать неопределённо долго. Для драйвера это опасно, особенно в production.

Рекомендация — ввести единый `TimeoutSettings` или `ClientOptions`.

---

### 23. Отсутствует полноценный публичный error hierarchy

Сейчас динамически создаются классы:

```python
type(name, (OperationFailure,), {...})
```

Недостатки:

- классы не имеют явных конструкторов;
- типы не видны статическому анализатору;
- нет свойств `labels`, `retryable`, `namespace`, `details`;
- неизвестные серверные коды не имеют структурированного fallback;
- тестировать все типы сложно.

Лучше иметь:

```python
class MongoError(OperationFailure): ...
class DuplicateKeyError(MongoError): ...
class DocumentValidationError(MongoError): ...
class TransientTransactionError(MongoError): ...
```

А таблицу кодов использовать только для выбора класса.

---

## Архитектурные пожелания

### 1. Ввести чёткие слои

Рекомендуемая структура:

```text
kover/
├── api/
│   ├── client.py
│   ├── database.py
│   └── collection.py
├── documents/
│   ├── model.py
│   ├── serialization.py
│   └── schema.py
├── protocol/
│   ├── wire.py
│   ├── bson.py
│   └── compression.py
├── topology/
│   ├── pool.py
│   ├── selector.py
│   └── monitor.py
├── transactions/
│   ├── session.py
│   ├── transaction.py
│   └── retry.py
├── errors/
│   ├── base.py
│   ├── mapping.py
│   └── codes.py
└── commands/
    ├── models.py
    └── builders.py
```

Сейчас `models`, `network`, `schema`, `client` и `collection` частично пересекаются по ответственности.

---

### 2. Ввести неизменяемые command objects

Вместо повсеместных `dict[str, Any]` стоит использовать typed command-модели:

```python
class InsertCommand(TypedDict):
    insert: str
    documents: list[MongoDocument]
    ordered: bool
```

Это позволит:

- валидировать команды до отправки;
- уменьшить количество ручных словарей;
- улучшить IDE/type checker;
- упростить тестирование wire payload.

---

### 3. Разделить MongoDB-документ и JSON-документ

Сейчас `DictT` используется даже там, где реально передаются BSON-типы:

- `ObjectId`;
- `Binary`;
- `Decimal128`;
- `Int64`;
- `datetime`.

Нужно использовать понятие `BsonValue`, иначе текущая типизация не отражает реальный протокол.

---

### 4. Добавить contract tests против MongoDB

Unit-тесты проходят:

```text
104 passed, 17 subtests passed
```

Но значительная часть наиболее опасных мест относится к реальному серверу:

- replica set failover;
- authentication negotiation;
- transaction retry;
- cursor cleanup;
- BSON subtype;
- validation schema;
- connection pool race conditions.

Нужен CI с MongoDB replica set, например через Docker/тестовый сервис, и отдельные наборы:

- standalone MongoDB;
- replica set;
- authentication enabled;
- TLS;
- compressed wire;
- MongoDB versions matrix.

---

### 5. Уточнить совместимость с MongoDB-версиями

Генератор схемы и некоторые команды зависят от версии MongoDB. Сейчас не видно слоя capability detection.

Стоит добавить:

```python
ServerCapabilities(
    max_wire_version=...,
    supports_bulk_write=...,
    supports_transactions=...,
    supports_json_schema=...,
)
```

И проверять возможности до отправки команд.

---

### 6. Улучшить observability

Для production-драйвера полезны:

- logging hooks;
- command monitoring;
- request IDs;
- server address;
- duration;
- pool wait time;
- connection creation/close events;
- transaction state transitions.

Сейчас большая часть диагностической информации теряется внутри `MongoTransport` и `ConnectionPool`.

## Приоритетный план доработок

### Сначала исправить

1. Убрать мутацию входных словарей из `Document.from_document()` и CRUD.
2. Исправить выбор `SCRAM-SHA-1`.
3. Заменить runtime `assert` на явные исключения.
4. Исправить обработку `TransientTransactionError`.
5. Добавить тесты на:
   - повторный `from_document`;
   - сохранение входного payload;
   - вставку документа с `_id`;
   - отсутствие `SCRAM-SHA-1`;
   - неверную SCRAM-подпись;
   - SHA-1 mismatch;
   - race в `create_if_not_exists`.

### Затем

6. Ввести отдельные типы MongoDB BSON-документов.
7. Разделить транспорт, wire protocol и авторизацию.
8. Сделать полноценную state machine транзакций.
9. Добавить timeouts и retry policies.
10. Реализовать topology/server selection.

### После этого

11. Сделать генератор схемы немутирующим и предупреждающим о потерянных ограничениях.
12. Унифицировать сериализацию моделей.
13. Сделать typed command layer.
14. Добавить replica-set CI и compatibility matrix.

Главный архитектурный риск проекта сейчас — не отсутствие функций, а смешение уровней: модели, сериализация, wire protocol, pool и транзакции напрямую знают детали друг о друге. Для текущего размера проекта это ещё управляемо, но дальнейшее расширение будет быстро увеличивать количество скрытых регрессий.