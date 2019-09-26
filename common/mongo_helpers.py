import logging
from typing import Union, Type
from uuid import uuid4, UUID

import pymongo
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorCollection

from api.server.utils import problems

logger = logging.getLogger(__name__)
ignore_mongo_id = {'_id': False}


async def mongo_filter(model: Union[Type[BaseModel], Type[dict]],
                       item_id: Union[UUID, str]):
    """
    Generates a mongo filter by the item_id appropriate to the model

    :param model: Class which the JSON in the collection represents
    :param item_id: UUID or name of desired item
    :return: dict which acts as a mongo filter
    """
    identifier = "id_" if type(item_id) is UUID else model._secondary_id
    return {identifier: item_id}


async def id_and_name(model: Union[Type[BaseModel], Type[dict]],
                      obj: BaseModel):
    """
    Returns a string of the form 'name (UUID)'

    :param model: Class which the JSON in the collection represents
    :param obj: Instance of above class
    :return: string of the form 'name (UUID)'
    """
    return f"{getattr(obj, model._secondary_id)} ({obj.id_})"


async def get_all_items(collection: AsyncIOMotorCollection,
                        model: Type[BaseModel],
                        *,
                        page: int = 1,
                        num_per_page: int = 20,
                        query: dict = None,
                        projection: dict = None):
    """
    Retrieve all items from a collection

    :param collection: Collection to query
    :param model: Class which the JSON in the collection represents
    :param page: Page number to retrieve.  #ToDo: implement correct server-side pagination
    :param num_per_page: Number of items per page to retrieve. Defaults to 20.
    :param query: Return only objects that contain the query
    :param projection: Filter to exclude keys from each result
    :return: List of objects in the collection
    """

    projection = {} if projection is None else projection
    projection.update(ignore_mongo_id)

    collection_json = await collection.find(filter=query, projection=projection) \
        .skip((page-1) * num_per_page) \
        .limit(num_per_page) \
        .to_list(None)
    return [model(**item_json) for item_json in collection_json]


async def get_item(collection: AsyncIOMotorCollection,
                   model: Union[Type[BaseModel], Type[dict]],
                   item_id: Union[UUID, str],
                   *,
                   query: dict = None,
                   projection: dict = None,
                   raise_exc: bool = True):
    """
    Retrieve a single item from a collection

    :param collection: Collection to query
    :param model: Class which the JSON in the collection represents
    :param item_id: UUID or name of desired item
    :param query: Return only objects that contain the query
    :param projection: Filter to exclude from mongo query result
    :param raise_exc: Whether to raise exception if item is not found.
    :return: Requested object from collection
    """
    try:
        item_id = UUID(item_id)
    except:
        item_id = item_id
    projection = {} if projection is None else projection
    projection.update(ignore_mongo_id)

    query = {} if query is None else query
    query.update(await mongo_filter(model, item_id))

    item_json = await collection.find_one(query, projection=projection)

    if item_json is None and raise_exc:
        raise problems.DoesNotExistException("read", model.__name__, await mongo_filter(model, item_id))
    elif model is dict or item_json is None:
        return item_json
    else:
        return model(**item_json)


async def create_item(collection: AsyncIOMotorCollection,
                      model: Union[Type[BaseModel], Type[dict]],
                      new_item_obj: BaseModel,
                      *,
                      projection: dict = None,
                      raise_exc: bool = True):
    """
    Create an item in the collection

    :param collection: Collection to query
    :param model: Class which the JSON in the collection represents
    :param new_item_obj: Object to place in collection
    :param projection: Filter to exclude from mongo query result
    :param raise_exc: Whether to raise exception if item cannot be created.
    :return: Created object in collection
    """
    try:
        if not new_item_obj.id_:
            new_item_obj.id_ = uuid4()
        r = await collection.insert_one(dict(new_item_obj))
        if r.acknowledged:
            return await get_item(collection, model, new_item_obj.id_, projection=projection, raise_exc=False)
    except pymongo.errors.DuplicateKeyError:
        if raise_exc:
            raise problems.UniquenessException("create", model.__name__, await id_and_name(model, new_item_obj))


async def update_item(collection: AsyncIOMotorCollection,
                      model: Union[Type[BaseModel], Type[dict]],
                      old_item_id: Union[UUID, str],
                      new_item_obj: BaseModel,
                      *,
                      projection: dict = None,
                      raise_exc: bool = True):
    """
    Update an item in the collection

    :param collection: Collection to query
    :param model: Class which the JSON in the collection represents
    :param old_item_id: UUID or name of item to replace
    :param new_item_obj: Object to place in collection
    :param projection: Filter to exclude from mongo query result
    :param raise_exc: Whether to raise exception if item is not found.
    :return: Updated object in collection
    """
    old_item_obj = await get_item(collection, model, old_item_id, projection=projection, raise_exc=False)
    if old_item_obj is None and raise_exc:
        raise problems.DoesNotExistException("update", model.__name__, old_item_id)

    try:
        new_item_obj.id_ = old_item_obj.id_
        r = await collection.replace_one(await mongo_filter(model, old_item_id), dict(new_item_obj))
        if r.acknowledged:
            return await get_item(collection, model, old_item_id, projection=projection, raise_exc=False)
    except pymongo.errors.DuplicateKeyError:
        if raise_exc:
            id_name = f"{await id_and_name(model, old_item_obj)} -> " \
                      f"{await id_and_name(model, new_item_obj)}"
            raise problems.UniquenessException("update", model.__name__, id_name)


async def delete_item(collection: AsyncIOMotorCollection,
                      model: Union[Type[BaseModel], Type[dict]],
                      old_item_id: Union[UUID, str],
                      *,
                      projection: dict = None,
                      raise_exc: bool = True):
    """
    Delete an item in the collection

    :param collection: Collection to query
    :param model: Class which the JSON in the collection represents
    :param old_item_id: UUID or name of item to delete
    :param projection: Filter to exclude from mongo query result
    :param raise_exc: Whether to raise exception if item is not found.
    :return: Whether the item was deleted
    """
    old_item_json = await get_item(collection, model, old_item_id, projection=projection, raise_exc=False)
    if old_item_json is None and raise_exc:
        raise problems.DoesNotExistException("delete", model.__name__, old_item_id)
    else:
        r = await collection.delete_one(await mongo_filter(model, old_item_id))
        return r.acknowledged
