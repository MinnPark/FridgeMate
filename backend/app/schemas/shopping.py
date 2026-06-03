from pydantic import BaseModel


class CartItem(BaseModel):
    ingredient: str
    product_name: str
    quantity: str
    price: int
    deeplink: str
