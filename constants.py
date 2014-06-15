# -*- coding: utf-8 -*-
from helpers.helpers import get_config

config = get_config()

CONSUMER_KEY = config.get('credentials', 'CONSUMER_KEY')
CONSUMER_SECRET = config.get('credentials', 'CONSUMER_SECRET')
ACCESS_TOKEN = config.get('credentials', 'ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = config.get('credentials', 'ACCESS_TOKEN_SECRET')

class TweetType:
    '''Tweet Types:
     - original tweet OT
     - conversational tweet CT
     - repeated tweet RT
    '''
    OT, CT, RT = range(3)

class UM:
    '''User Metrics computed for each potential authority:
     * OT1 - Number of original tweets
     * OT2 - Number of links shared
     * OT3 - Self-similarity score that computes how similar is
             author's recent tweet w.r.t her previous tweets
     * OT4 - Number of keyword hashtags used
     * CT1 - Number of conversational tweets
     * CT2 - Number of conversational tweets where conver-
             sation is initiated by the author
     * RT1 - Number of retweets of other's tweet
     * RT2 - Number of unique tweets (OT1) retweeted by other users
     * RT3 - Number of unique users who retweeted author's tweets
     * M1  - Number of mentions of other users by the author
     * M2  - Number of unique users mentioned by the author
     * M3  - Number of mentions by others of the author
     * M4  - Number of unique users mentioning the author
     * G1  - Number of topicaly active followers
     * G2  - Number of topicaly active friends
    '''
    OT1, OT2, OT3, OT4 = 'OT1', 'OT2', 'OT3', 'OT4'
    CT1, CT2 = 'CT1', 'CT2'
    RT1, RT2, RT3 = 'RT1', 'RT2', 'RT3'
    M1, M2, M3, M4 = 'M1', 'M2', 'M3', 'M4'
    G1, G2 = 'G1', 'G2'

class UF:
    '''User Features computed from metrics. See
    IdentifyingTopicalAuthoritiesInMicroblogs.pdf paper for details.

                          OT1 + CT1 + RT1
    TS - Topical Signal = ---------------
                             #tweets
         estimates the degree of the author's involvement in the topic

                               OT1
    SS - Signal Strength = -----------
                            OT1 + RT1
         estimates how original is the author; for a true authority
         this should be close to 1.

                                OT1          CT1 - CT2
    nCS - Non-Chat Signal = ----------- + λ -----------
                             OT1 + CT1        CT1 + 1
          λ - is a param that is wanted to be chosen so that:
                    OT1
          nCS < -----------
                 OT1 + CT2

         #TODO

    RI - Retweet Impact = RT2 log(RT3)
         so penalize greatly when RT3 is small (a small
         number of unique users who repeatedly retweet,
         so that RT2 is big)

    MI - Mention impact = max(M3*log(M4) - M1*log(M2), 0)
         does discard the mentions that ones said
         about the author out of courtesy because author
         said about others too.
         Estimates how much an author is genuinely mentioned.
    '''
    TS, SS, nCS, RI, MI = range(5)

# Minimum number of tweets a user must have in order to be
# considered as potential authority in algorithm.
MIN_TWEETS_USER = 10

MAX_FRIENDS = 100000
MAX_FOLLOWERS = 100000

nCS_LAMBDA = 0.05

# MongoDB specifics.

SAMPLE_COLLECTION = 'tweets_en'
COLLECTION = 'tweets_test'
COLLECTION_USERS = 'tweets_users'

DATABASE_NAME = 'licenta'
