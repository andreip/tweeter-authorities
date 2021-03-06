Summary
---

Find authorities for Twitter topics. Needs to download tweets (fetching stage), then it can compute based on fetched tweets.
Requirements:
* the implementation uses mongodb to store downloaded tweets
* see requirements.txt for more, but main packages used are: pymongo, tweepy, scikit-learn, numpy, scipy

See results from datasets included in `dump/licenta` folder. Results are in `.html` files in `dump/licenta/results/` folder. These results have been obtained with the current code, by using only `Retweet Impact` and `Mention Impact` features, see `paper/` folder for way more details and how we combined the metrics and analyzed results.

Usage
---
1. populate mongoDB database with tweets
  * use existing tweets in `dump/` folder. Import by using the `dump/import.sh` script like so:
    * have a `mongod` running instance before running the script
    * run the script from root folder like `$ ./dump/import.sh` and you're done.
    * verify in mongod that you have successfully imported the data and the features+metrics:
    ```mongo
    > db.getCollection("halep").count()  # 2736`
    > db.getCollection("ukraine gas russia").count()  # 16203
    ```
  * or fetch it yourself like say for topic "ukraine gas russia":
  ```bash
  # tells it to fetch a maximum of 100 pages x 100 per page => 10,000 tweets.
  $ ./main.py fetch "ukraine gas russia" 100
  ```
  
2. after we've added tweets in mongoDB, we can compute authorities for the collected tweets:

  ```bash
  # 2nd param should be a valid collection in mongoDB containing tweets.
  # should give us the main authorities by processing all tweets from mongo collection "ukraine gas russia".
  ./main.py compute "ukraine gas russia"
  ```
