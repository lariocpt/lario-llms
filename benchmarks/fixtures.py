"""Public deterministic fixtures. No production conversation or KB content."""
import base64
import io

VERSION = 1

CODING = [
    ("deduplicate", "def solve(values):\n    return sorted(set(values))\n", "Return unique values in first-seen order.", [([3,1,3,2], [3,1,2]),([],[])]),
    ("median", "def solve(values):\n    return sorted(values)[len(values)//2]\n", "Return numeric median, averaging the middle two for even length; return None for empty.", [([4,1,2,3],2.5),([],None),([9],9)]),
    ("palindrome", "def solve(value):\n    return value == value[::-1]\n", "Ignore case and non-alphanumeric characters when detecting a palindrome.", [("A man, a plan, a canal: Panama",True),("abc",False)]),
    ("flatten", "def solve(values):\n    return values\n", "Flatten arbitrarily nested lists, keeping other values including None and empty strings.", [([1,[2,[3]],None,""],[1,2,3,None,""]),([],[])]),
    ("frequency", "def solve(values):\n    return dict.fromkeys(values,1)\n", "Return a dictionary of counts, including repeated and negative integers.", [([1,1,-2],{1:2,-2:1}),([], {})]),
    ("chunks", "def solve(values, size):\n    return [values]\n", "Split a list into chunks of positive size; return [] for empty input; raise ValueError for size <= 0.", [(([1,2,3,4,5],2),[[1,2],[3,4],[5]]),(([],2),[])]),
    ("merge_intervals", "def solve(values):\n    return values\n", "Merge overlapping or touching [start,end] intervals; output sorted, without modifying input.", [([[5,7],[1,3],[3,6]],[[1,7]]),([],[])]),
    ("slug", "def solve(value):\n    return value.lower().replace(' ','-')\n", "Produce a lowercase ASCII slug: replace each run of non-alphanumeric characters with one hyphen and trim hyphens.", [("  Hello,   World!  ","hello-world"),("---","")]),
    ("brackets", "def solve(value):\n    return value.count('(')==value.count(')')\n", "Check properly nested (), [] and {} brackets, ignoring other characters.", [("([{}])",True),("([)]",False),(")(",False)]),
    ("binary_search", "def solve(values, target):\n    return 0\n", "Return the leftmost target index in a sorted list, or -1 if absent.", [(([1,2,2,4],2),1),(([],2),-1),(([1,3],2),-1)])
]


def text_cases():
    return [{"id":"latency-8k","kind":"latency","prompt":"Read this repeated synthetic log, then write 256 words explaining how to preserve ordering when deduplicating records.\n"+"record id=17 category=test status=accepted\n"*1000},
            {"id":"latency-short","kind":"latency","prompt":"Write 256 words explaining the difference between a process being ready and returning a correct answer."}]


def tools():
    cases=[]
    for i in range(10):
        a,b=i*7+1,i*3+2
        cases.append({"id":f"tool-{i}","kind":"tool","a":a,"b":b,"expected":a+b})
    return cases


def vision_cases():
    from PIL import Image, ImageDraw, ImageFont
    font_path='/usr/share/fonts/TTF/DejaVuSans.ttf'
    try: font=ImageFont.truetype(font_path,52)
    except OSError: font=ImageFont.load_default(size=52)
    cases=[]
    def image_url(image):
        buffer=io.BytesIO(); image.save(buffer,'PNG')
        return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    for i in range(12):
        image=Image.new('RGB',(2400,1800),'white'); draw=ImageDraw.Draw(image)
        ident=f'INV-{73142+i}'; total=f'{286+i}.75'
        draw.text((120,150),f'INVOICE {ident}\nGrand total: {total}\nPaid: NO',font=font,fill='black',spacing=30)
        cases.append({'id':f'ocr-{i}','kind':'vision','images':[image_url(image)],
                      'prompt':'Read the invoice identifier, grand total and payment status. Return only JSON with invoice, total and paid.',
                      'expected':{'invoice':ident,'total':total,'paid':'NO'}})
    for i in range(8):
        images=[]
        for x in [200,1000]:
            image=Image.new('RGB',(1600,1000),'white');draw=ImageDraw.Draw(image)
            draw.rectangle((x,200,x+200,400),fill='red'); draw.ellipse((300,600,450,750),fill='blue')
            images.append(image_url(image))
        cases.append({'id':f'frames-{i}','kind':'description','images':images,
                      'prompt':'Compare these two ordered frames. Describe the moving red square and stationary blue circle, including movement direction.',
                      'required':['red','square','blue','circle','right']})
    return cases


def rag_documents():
    return [f'Synthetic system UNIT-{i:02d}: its approved recovery code is TOKEN-{i:02d}-SAFE. '
            f'Only UNIT-{i:02d} uses this exact code; do not substitute another unit.' for i in range(10)]
