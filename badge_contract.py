"""Shared Qt-independent geometry and opaque-color contract for source badges."""
MIN_WIDTH = 104
WIDTH = 160  # Preferred maximum; measured card spacing may require less.
HEIGHT = 52
GAP = 8
TIER_ROW_HEIGHT = 32
HINT_FONT_SIZE = 11
OPAQUE_RGB = (11, 20, 30)
HORIZONTAL_GAP = 2  # Minimum logical separation; top-to-card gap remains 8 DIP.


def choose_width(centers, dpr):
    """Fit original measured card centers, without changing tier text size."""
    import math
    if len(centers)!=3 or not math.isfinite(dpr) or dpr<=0:
        raise ValueError('Invalid badge spacing')
    available=math.floor(min(centers[i+1]-centers[i] for i in range(2))/dpr-HORIZONTAL_GAP)
    if available<MIN_WIDTH:raise ValueError('Insufficient card spacing')
    return min(WIDTH,available)


def align_physical_regions(physical, dpr, logical_width):
    """Snap three local child origins to Qt's logical grid and ceil its hull.

    Input is absolute physical (x,y,width,height) rectangles. Output is the
    absolute physical hull and local physical regions. X origins round nearest;
    Y origins round upward so the card-top clearance can never decrease.
    """
    import math
    left=min(p[0] for p in physical);top=min(p[1] for p in physical)
    origins=tuple((round((p[0]-left)/dpr),math.floor((p[1]-top)/dpr)) for p in physical)
    regions=tuple((round(lx*dpr),round(ly*dpr),p[2],p[3]) for (lx,ly),p in zip(origins,physical))
    # Separately rounded native origin and ceil-sized region can extend one
    # physical pixel past the direct logical edge. Include that exact extent,
    # then round the parent up to a complete logical unit as well.
    logical_right=max(max(lx+logical_width for lx,ly in origins),math.ceil(max(x+w for x,y,w,h in regions)/dpr))
    logical_bottom=max(max(ly+HEIGHT for lx,ly in origins),math.ceil(max(y+h for x,y,w,h in regions)/dpr))
    width=math.ceil(logical_right*dpr)
    height=math.ceil(logical_bottom*dpr)
    return (left,top,width,height),regions


def top_gap(dpr):
    """At least 8 DIP and 8 physical pixels, including sub-100% app scaling."""
    return max(GAP*dpr,8)


def logical_hull_from_physical(width, height, dpr):
    """Invert our ceil projection without applying ceil a second time.

    Example:623DIP at1.25 becomes779px, not624DIP/780px.
    """
    import math
    logical=tuple(math.floor(value/dpr+1e-9) for value in (width,height))
    if any(value<=0 for value in logical) or tuple(math.ceil(value*dpr-1e-9) for value in logical)!=(width,height):
        raise ValueError('Physical badge hull is not a canonical logical projection')
    return logical
