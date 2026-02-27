from pydantic import BaseModal
from typing import Any,Dict,List,Optional

class CompleteLessonReq(BaseModal):
    subtopic_id:int

class LessonItem(BaseModal):
    id:str
    