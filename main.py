#!/usr/bin/env python
# -*- coding: utf-8 -*-

from google.appengine.ext import webapp, db
from google.appengine.ext.webapp import util, template
from google.appengine.api import memcache, urlfetch, memcache
from google.appengine.api.labs import taskqueue

import datetime
import os
import random
import re
import sys
from ConfigParser import SafeConfigParser

import twoauth

from twilog import twilog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from markovchains import MarkovChains

### 文字コード設定 ###
stdin = sys.stdin
stdout = sys.stdout
reload(sys)
sys.setdefaultencoding('utf-8')
sys.stdin = stdin
sys.stdout = stdout
######################


## 定数（ツイートの種類）
USE_FILE = 1
USE_MARKOV = 2

"""
OAuth の各種キーを読み込む
"""
parser = SafeConfigParser()
parser.readfp(open('config.ini'))
sec = 'oauth'
consumer_key = parser.get(sec, 'consumer_key')
consumer_secret = parser.get(sec, 'consumer_secret')
access_token = parser.get(sec, 'access_token')
access_token_secret = parser.get(sec, 'access_token_secret')

sec = 'twilog'
original_id = parser.get(sec, 'original_id')

sec = 'bot'
tweet_type = int(parser.get(sec, 'tweet_type'))
markov = MarkovChains()
bot_name = parser.get(sec, 'screen_name') #Hemus

api = twoauth.api(consumer_key,
                  consumer_secret,
                  access_token,
                  access_token_secret)

class DoReply(db.Model):
    flg = db.BooleanProperty()

def parse_tweet(text):
    reply = re.compile(u'@[\S]+')
    hashtag = re.compile(u'#[\S]+')
    url = re.compile(r's?https?://[-_.!~*\'()a-zA-Z0-9;/?:@&=+$,%#]+', re.I)

    #Hemus
    retweet = re.compile(u'RT\s@[\S]+') 
    text = retweet.sub('', text)

    text = reply.sub('', text)
    text = hashtag.sub('', text)
    text = url.sub('', text)
    text = text.replace(u'．', u'。')
    text = text.replace(u'，', u'、')
    text = text.replace(u'「', '')
    text = text.replace(u'」', '')
    text = text.replace(u'？', u'?')
    text = text.replace(u'！', u'!')
    return text

"""
POST された文章を元に新しい文章生成
"""
def get_sentence(sentence):
    markov.analyze_sentence(sentence)
    return markov.make_sentence()


"""
GET:  DB を元に生成した新しい文章を返す
POST: 投げられた文章を解析して DB に突っ込む
"""

def tweet_from_db():
    markov.load_db('gquery2')
    taskqueue.add(url='/task/talk')
    return markov.db.fetch_new_sentence()

def analyse_sentence_to_db(sentence):
    taskqueue.add(url='/learn_task',
            params={'sentences': sentence})

class Since(db.Model):
    id = db.IntegerProperty()

class PostTweetHandler(webapp.RequestHandler):
    def get(self):
        tweet = get_tweet(False)
        api.status_update(tweet)

    def post(self):
        tweet = get_tweet(False)
        api.status_update(tweet)

class ReplyTweetHandler(webapp.RequestHandler):
    def get_sinceid(self):
        since_id = memcache.get('since_id')
        if since_id is None:
            since = Since.get_by_key_name('since_id')
            if since is not None:
                since_id = since.id
        return since_id
    
    def set_sinceid(self, since_id):
        memcache.set('since_id', since_id)
        Since(key_name='since_id', id=int(since_id)).put()
        
    def get(self):
        mentions = api.mentions(since_id=self.get_sinceid())

        reply_temp_defeated = DoReply.get_by_key_name('id')
        if reply_temp_defeated is None:
            DoReply(key_name='id', flg=False).put()

        if mentions is not None:
            last_since_id = mentions[len(mentions)-1]['id']
            self.set_sinceid(last_since_id)

            for status in mentions:
                rand = random.randint(1,100)
                if rand <= 10: #1割の確率で返信しない
                    continue
                screen_name = status['user']['screen_name']
                tweet = get_tweet(True)
                tweet = "@%s %s" %(screen_name, tweet)
                last_since_id = status['id']
                if (not reply_temp_defeated.flg):
                    api.status_update(tweet, in_reply_to_status_id=last_since_id)

"""
added code : @HemusAran
Timelineを取得して特定ワードに自動返信
"""
class AutoReplyTweetHandler(webapp.RequestHandler):
    def get_sinceid(self):
        since_id = memcache.get('tl_since_id')
        if since_id is None:
            since = Since.get_by_key_name('tl_since_id')
            if since is not None:
                since_id = since.id
        return since_id
    
    def set_sinceid(self, since_id):
        memcache.set('tl_since_id', since_id)
        Since(key_name='tl_since_id', id=int(since_id)).put()

    def isReply(self, status):
        global bot_name
        if status['text'].find("RT") != -1:
            return 0
        if status['text'].find("@") != -1:
            return 0
        if status['user']['screen_name'] == bot_name:
            return 0
        return 1

    def auto_tweet(self, status, hitkey, sentence_text, percent):
        text = status['text']
        hit = 0
        for key in hitkey:
            if text.find(key) != -1:
                hit = 1
                break
 
        if hit == 1:
            rand = random.randint(1,100)
            if rand <= percent:
                last_since_id = status['id']
                screen_name = status['user']['screen_name']
                tweet = tweet_randomly_from_text(sentence_text)
                tweet = "@%s %s" %(screen_name, tweet)
                api.status_update(tweet, in_reply_to_status_id=last_since_id)
                return 1
        return 0

    def get(self):
        lUnko = ['unko', u'うんこ', u'ウンコ']
        lSleep = [u'寝る', u'眠る', u'寝ます', u'眠ります', u'おやすみ']
        tweets = api.home_timeline(since_id=self.get_sinceid(), count=200)

        if tweets is not None:
            last_since_id = tweets[len(tweets)-1]['id']
            self.set_sinceid(last_since_id)

            for status in tweets:
                if self.isReply(status) == 0:
                    continue
                if self.auto_tweet(status, lUnko, 'unko.txt', 100) == 1:
                    continue
                if self.auto_tweet(status, lSleep, 'sleep.txt', 50) == 1:
                    continue

class SinceIdHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write(str(memcache.get('since_id')))

class MainHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write('Hello World!')

class SettingHandler(webapp.RequestHandler):
    def get(self):
        reply_temp_defeated = DoReply.get_by_key_name('id')
        flg = False
        if reply_temp_defeated is None:
            DoReply(key_name='id', flg=False).put()
        else:
            flg = reply_temp_defeated.flg
        dic = {'reply_temp_defeated': flg}
        self.response.out.write(template.render('views/settings.html', dic))

    def post(self):
        _reply_temp_defeated = self.request.get('reply_temp_defeated')
        if _reply_temp_defeated == '1':
            DoReply(key_name='id', flg=False).put()
        else:
            DoReply(key_name='id', flg=True).put()
        reply_temp_defeated = DoReply.get_by_key_name('id')

        dic = {'reply_temp_defeated': reply_temp_defeated.flg}
        self.response.out.write(template.render('views/settings.html', dic))


### こっからマルコフ連鎖用 ###
"""
文章を生成してキューに貯める
"""
class ApiDbSentenceTalkTask(webapp.RequestHandler):
    def post(self):
        markov.load_db('gquery2')
        markov.db.store_new_sentence()

"""
文章を解析して DB に保存
"""
class ApiDbSentenceLearnTask(webapp.RequestHandler):
    def post(self):
        text = self.request.get('sentences')
        markov.load_db('gquery2')
        markov.db.store_sentence(text)

"""
memcache の中身を全削除
"""
class DeleteHandler(webapp.RequestHandler):
    def get(self):
        memcache.flush_all()

"""
Twilog から学習
"""
class LearnTweetHandler(webapp.RequestHandler):
    def get(self):
        if tweet_type == USE_MARKOV:
            yesterday = datetime.date.today() - datetime.timedelta(days=1)
            log = twilog.Twilog()
            tweets = log.get_tweets(original_id, yesterday)
            for tweet in tweets:
                text = parse_tweet(tweet)
                sentences = text.split(u'。')
                for sentence in sentences:
                    analyse_sentence_to_db(sentence)


"""
Twilog から学習（一括）
"""
class LearnTweetAllHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write(template.render('views/learn.html', {}))

    def post(self):
        s_year = int(self.request.get('s_year'))
        s_month = int(self.request.get('s_month'))
        s_day = int(self.request.get('s_day'))
        e_year = int(self.request.get('e_year'))
        e_month = int(self.request.get('e_month'))
        e_day = int(self.request.get('e_day'))

        start = datetime.date(s_year, s_month, s_day)
        end = datetime.date(e_year, e_month, e_day)

        while True:
            if start == end:
                break
            else:
                taskqueue.add(url='/task_alllearn',
                        params={'year':start.year, 'month': start.month,
                                'day':start.day})
                start = start + datetime.timedelta(days=1)
        self.response.out.write(template.render('views/learn_result.html', {}))
                       

class LearnTweetAllTask(webapp.RequestHandler):
    def post(self):
        year = int(self.request.get('year'))
        month = int(self.request.get('month'))
        day = int(self.request.get('day'))
        log = twilog.Twilog()
        tweets = log.get_tweets(original_id, datetime.date(year, month, day))
        for tweet in tweets:
            text = parse_tweet(tweet)
            sentences = text.split(u'。')
            for sentence in sentences:
                analyse_sentence_to_db(sentence)

"""
added code : @HemusAran
マルコフ連鎖で生成された文字列の表示
"""
class CheckSentenceHandler(webapp.RequestHandler):
    def get(self):
        objs = memcache.get('sentences')
        if objs is not None:
            for obj in objs:
                self.response.out.write(obj + '<BR>')
        else:
            self.response.out.write('NULL !!')

class TestCodeHandler(webapp.RequestHandler):
    def get(self):
        text = tweet_randomly_from_text('unko.txt')
        self.response.out.write(text+'<BR>')
        test = tweet_randomly_from_text('sleep.txt')
        self.response.out.write(test+'<BR>')


### ここまでマルコフ連鎖用 ###
"""
ツイート内容を決める

マルコフ連鎖を使う場合
=====
return tweet_from_db()
=====

ファイルに書かれてる文章をランダムにつぶやく
file: sentence.txt
=====
return tweet_randomly_from_text('sentence.txt')
=====
"""

def get_tweet(_reply=False):
    if _reply:
        if tweet_type == USE_FILE:
            return tweet_randomly_from_text('sentence.txt')
        elif tweet_type == USE_MARKOV:
            return tweet_from_db()
    else:
        if tweet_type == USE_FILE:
            return tweet_randomly_from_text('sentence.txt')
        elif tweet_type == USE_MARKOV:
            return tweet_from_db() 


#自動reply導入による複数テキスト記憶(連想配列)へ変更 HemusAran
dict = {}
def tweet_randomly_from_text(text):
    global dict
    sentences = dict.get('text')

    if sentences is None:
        sentences = []
        sentence = []
        for line in open(text).read().splitlines():
            if line.startswith('%'):
                if sentence != []:
                    sentences.append('\n'.join(sentence))
                    sentence = []
            else:
                sentence.append(line)
        if sentence != []:
            sentences.append('\n'.join(sentence))
        dict[text] = sentences

    return random.choice(sentences)


def main():
    application = webapp.WSGIApplication(
            [('/tweet', PostTweetHandler),
            ('/reply', ReplyTweetHandler),
            ('/autoreply', AutoReplyTweetHandler), #Hemus
            ('/since_id', SinceIdHandler),
            ('/task/talk', ApiDbSentenceTalkTask),
            ('/learn_task', ApiDbSentenceLearnTask),
            ('/delete_memcache', DeleteHandler),
            ('/learn', LearnTweetHandler),
            ('/learn_tweet_all', LearnTweetAllHandler),
            ('/task_alllearn', LearnTweetAllTask),
            ('/settings', SettingHandler),
            ('/check_sentence', CheckSentenceHandler), #Hemus
            ('/testcode', TestCodeHandler), #Hemus
            ('/', MainHandler),
            ],
    debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
    
