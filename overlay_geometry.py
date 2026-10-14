"""Pure physical-pixel bounds for the overlay's OWN Qt logical layout.

Does not authorize or perform capture. Negative desktop origins are valid.
The application's effective DPR may differ from the selected game's DPI.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class LayoutBudget:
    logical_width:int
    logical_height:int
    margin:int
    dpr:float

def layout_budget(rect,dpr):
    values=(rect.x,rect.y,rect.width,rect.height)
    if any(not isinstance(v,int) or isinstance(v,bool) for v in values) or min(rect.width,rect.height)<=0:raise ValueError('无效的目标客户区像素范围。')
    if not isinstance(dpr,(int,float)) or isinstance(dpr,bool) or not math.isfinite(dpr) or not .5<=dpr<=10:raise ValueError('无法取得叠加窗口自身的有效缩放比例。')
    margin=max(2,min(math.ceil(12*dpr),rect.width//12,rect.height//12))
    width=math.floor((rect.width-2*margin)/dpr);height=math.floor((rect.height-2*margin)/dpr)
    if width<280 or height<100:raise ValueError(f'目标客户区 {rect.width}×{rect.height} 像素，叠加缩放 {dpr:g} 倍；可用布局 {width}×{height}，不足以清晰显示三项。')
    return LayoutBudget(min(820,width),height,margin,float(dpr))

def placement(rect,budget,logical_height):
    if not isinstance(logical_height,int) or isinstance(logical_height,bool) or not 1<=logical_height<=budget.logical_height:raise ValueError('资料文字在当前客户区中无法完整显示。')
    width=math.ceil(budget.logical_width*budget.dpr);height=math.ceil(logical_height*budget.dpr)
    x=rect.x+(rect.width-width)//2;y=rect.y+rect.height-height-budget.margin
    if not (rect.x<=x and rect.y<=y and x+width<=rect.x+rect.width and y+height<=rect.y+rect.height):raise ValueError('计算出的资料卡范围越过目标客户区。')
    return x,y,width,height
