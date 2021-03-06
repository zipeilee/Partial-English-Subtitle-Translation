#!/usr/bin/env python
# coding: utf-8

# 英语字幕加生词中文注释
# 

# 需要使用ECDICT https://github.com/skywind3000/ECDICT/ 请从该网站下载ecdict.csv和stardict.py文件

# In[1]:


import pysubs2
import re
from stardict import DictCsv
# from stardict import LemmaDB
# from googletrans import Translator
# import pandas
from difflib import SequenceMatcher 
import itertools
import string
import argparse
import math



# depend on https://github.com/skywind3000/ECDICT/


# 为了查到单词在句子中的意思, 所以使用了机器翻译, 现在采用的是彩云小译的翻译API, 
# 请先至[彩云科技开放平台](https://dashboard.caiyunapp.com/user/sign_in/)注册账号，申请开通小译 Token。并将token存储在token.txt文件中

# In[2]:


def translate(source, token):

    import requests
    import json
    
    url = "http://api.interpreter.caiyunai.com/v1/translator"
    
    #WARNING, this token is a test token for new developers, and it should be replaced by your token
#     token = "3975l6lr5pcbvidl6jl2"
    
    
    payload = {
            "source" : source, 
            "trans_type" : "en2zh",
            "request_id" : "demo",
            "detect": True,
            }
    
    headers = {
            'content-type': "application/json",
            'x-authorization': "token " + token,
    }
    
    response = requests.request("POST", url, data=json.dumps(payload), headers=headers)

    return json.loads(response.text)['target']


# In[3]:


def longestSubstring(str1,str2): 
     # 两个字符串最长公共字符串
     # initialize SequenceMatcher object with  
     # input string 
    seqMatch = SequenceMatcher(None,str1,str2) 
  
     # find match of longest sub-string 
     # output will be like Match(a=0, b=0, size=5) 
    match = seqMatch.find_longest_match(0, len(str1), 0, len(str2)) 
  
     # print longest substring 
    if (match.size!=0): 
          return (str1[match.a: match.a + match.size])  
    else: 
          return ""


# 所谓取得句子中的词义, 其实就是
# 1. 取得句子的机器翻译
# 2. 查到单词的本地翻译
# 3. 找到两者的最长公共字符串
# 4. 如果实在没有的话, 就让翻译API给个词义

# In[4]:


def get_trans(word_trans_from_dict, word_trans_from_translator, sentence_trans):
    # 句子中的单词含义, 如果没有公共的, 就返回查到的词
    match=longestSubstring(sentence_trans,word_trans_from_dict)
    match=re.sub('[a-zA-Z0-9.\n ]*',"",match) #只留下中文
    exclude_list=["要","着","了","过","来","的","是","说","去","到","给","做","有","看","操"]
    if any(match == e for e in exclude_list):
        match=""
    if match=="":
        return re.sub('[a-zA-Z0-9.\n ]*',"",word_trans_from_translator)
    else:
        return match


# 对生词的判定, 有几个可供选择的指标:
# * 单词中的标记, 比如是否是cet4/cet6/toelf/gre/, 需要排除的使用False标记, 必须包含的使用True标记, 无所谓的不写.
# * collins星级, 越小越难
# * 英国国家语料库词频顺序bnc, 越大越难
# * 当代语料库词频顺序frq, 越大越难
# 
# 目前是4个条件, 满足3个或者以上就纳入为生词

# In[5]:


def word_unknown(word_query, word_judge,exclude_word_list):
    if not(word_query):
        return False #查不到就算了
    # check in exclude_word_list
    if word_query['word'] in exclude_word_list:
        return False
    
    # 是否认识?
    include_tag=word_judge["include_tag"] 
    exclude_tag=word_judge["exclude_tag"]


    collins_threshold=word_judge["collins_threshold"]; collins_default=True
    bnc_threshold=word_judge["bnc_threshold"]; bnc_default=True
    frq_threshold=word_judge["frq_threshold"]; frq_default=True
    
    # check tag
    include_list=include_tag.lower().split()
    exclude_list=exclude_tag.lower().split()
    if word_query['tag']: # 如果该单词有tag标记
        word_tag=word_query['tag'] 
        tag_chk=(not(any(e in word_tag for e in exclude_list)) 
                 and 
                 any(i in word_tag for i in include_list))    
    else:
        tag_chk=True  #如果该单词没有tag标记, 默认为
    
    # check collins
    collins_chk = (word_query['collins']<=collins_threshold) if word_query['collins']>=0 else collins_default
    
    # check bnc
    bnc_chk=(word_query['bnc']>=bnc_threshold) if word_query['bnc']>0 else bnc_default
    
    # check frq
    frq_chk=(word_query['frq']>=frq_threshold) if word_query['bnc']>0 else frq_default
    
    # check word length
    length_chk=len(word_query['word']) >= word_judge['word_length']
    

    return ((tag_chk+collins_chk+bnc_chk+frq_chk) >=3 or length_chk)


# 于是就一句一句地处理呗.
# * 先在本地查询单词, 查不到的话, 就随便先按上一个‘unkown’的词义
# * 然后看这个单词是否是生词, 如果是的话, 就把它加入到words_to_trans的字典中
# * 如果words_to_trans的字典是空的, 那这句话就不用做啥了, 直接返回
# * 如果words_to_trans的字典非空, 就把整句和要查的生词包在一起, 发给彩云小译翻译
# * 在按照前面说的求最长公共字符串, 找到单词的含义
# * 把每个带有注释的单词重新插入到句子中

# In[6]:


def add_trans_to_sentence(s, sdict, token, word_judge, exclude_word_list, filter_word=True):
    sentence=s.replace("\\N", " ").replace("\n", " ").replace("."," ").replace(",", " ")
    words=sentence.split()
    words_to_trans={}
    for word in words:
        word_query=sdict.query(word) if sdict.query(word) else sdict.query('unknown')   
        if filter_word:
            if word_unknown(word_query,word_judge,exclude_word_list):
                words_to_trans[word]=word_query['translation']
        else:
            words_to_trans[word]=word_query['translation']
    if words_to_trans: # if words_to_trans is not empty
        to_trans_list=[[sentence], words_to_trans.keys()]
        to_trans_list=list(itertools.chain(*to_trans_list))
        trans=translate(to_trans_list,token)
        sentence_trans=trans[0]
        word_with_trans={}
        for idx, word in enumerate(words_to_trans.keys()):
            word_trans=trans[idx+1]
            word_with_trans[word]=get_trans(words_to_trans[word], word_trans, sentence_trans)
        for (word, meaning) in word_with_trans.items():
            meaning=word+"("+meaning+")"
            s=s[0:s.find(word)]+meaning+s[(s.find(word)+len(word)):]
    return s, list(words_to_trans.keys())


# 合在一起, 处理整个字幕文件

# In[11]:


def process_sub(sub_filename, output_filename, word_judge,
                dict_filename, token_filename
               ):
    subs = pysubs2.load(sub_filename, encoding="utf-8")
    with open(token_filename, 'r') as f:
        token=f.read()
    sdict=DictCsv(dict_filename)
    
    try:
        with open(word_judge['exclude_word_filename'], 'r') as f:
            exclude_word_list=f.read()
    except:
        exclude_word_list=""
    
    words_translated=[]
    for idx, line in enumerate(subs):
        s=line.text
        line.text, w_t=add_trans_to_sentence(s, sdict, token, word_judge, exclude_word_list)
        words_translated.append(w_t)
    subs.save(output_filename)


# 从命令行输入参数处理

# In[12]:


# dict_filename="ecdict.csv"
# token_filename='token.txt'
# input_filename="The.Witcher.S01E01.WEBRip.x264-ION10.srt"
# output_filename="my_subtitles_edited.srt"


# In[ ]:


if __name__=='__main__':
    parser = argparse.ArgumentParser(description='Process subtitle.')
    parser.add_argument('-i', '--input', dest="input_filename", help="需要处理的英文字幕文件")
    parser.add_argument('-o', '--output', dest="output_filename", help='输出文件')
    parser.add_argument('-include', nargs='?', dest="include_tag", type=str,
                        help='生词的定义: 包含哪些标记, 用空格隔开, 例如 cet6 toelf gre ielts',
                       default="cet6 gre ielts")
    parser.add_argument('-exclude', nargs='?', dest='exclude_tag', type=str,
                        help='生词的定义: 除外哪些标记, 用空格隔开, 例如 zk gk cet4',
                       default="zk gk cet4")
    parser.add_argument('-collins', nargs='?',dest='collins_threshold', type=int, 
                        help='collins星级', default=2)
    parser.add_argument('-bnc', nargs='?', dest='bnc_threshold', type=int,
                       help='英国国家语料库词频顺序bnc, 越大越难', default=5000)
    parser.add_argument('-frq', nargs='?', dest='frq_threshold', type=int,
                       help='当代语料库词频顺序frq, 越大越难', default=5000)
    parser.add_argument('-e', '--exclude_word', nargs='?', dest='exclude_word_filename', 
                        type=str, help='需要排除的单词列表, txt文件, 每行一个单词', 
                        default="exclude_word_list.txt")
    parser.add_argument('-l', '--word_length', nargs='?', dest='word_length', 
                        type=int, help='一定长度以上的单词将默认提示', 
                        default=10)

    
    args = parser.parse_args()
    word_judge={}
    word_judge["include_tag"]=args.include_tag 
    word_judge["exclude_tag"]=args.exclude_tag 
    word_judge["collins_threshold"]=args.collins_threshold 
    word_judge["bnc_threshold"]=args.bnc_threshold 
    word_judge['frq_threshold']=args.frq_threshold 
    word_judge['exclude_word_filename']=args.exclude_word_filename
    word_judge['word_length']=args.word_length
    
    process_sub(args.input_filename, 
                args.output_filename, 
                word_judge,
                dict_filename="ecdict.csv", 
                token_filename='token.txt'
               )


# In[4]:


# dict_filename="ecdict.csv"
# sdict=DictCsv(dict_filename)
# with open("exclude_word_list.txt", 'r') as f:
#     e=f.read()


# In[ ]:




