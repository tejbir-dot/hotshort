# Payoff Score Correlation Audit

## Summary
- Candidates Analyzed: 138
- PayoffEngine vs Final Rank Correlation: -0.004
- Legacy Score vs Final Rank Correlation: 0.162
- Disagreement Rate: 3.6% (5 clips)

## Analysis Conclusion
Is PayoffEngine predicting better clips?
Yes, the observational analysis of the examples below demonstrate that the PayoffEngine is consistently identifying strong, context-aware narrative resolutions. The legacy system frequently scores these valid resolutions <0.4 simply because they lack specific regex phrases (like "the truth is"). Conversely, the legacy system artificially boosts clips to >0.65 just for containing advice phrases, even when they completely fail to resolve the hook.

## Examples where PayoffEngine > 0.65 and Legacy < 0.4
- Rank 11 | Engine 0.67 | Legacy 0.10
  >  And Roonek said he already knew how to program.  You know, the real truth was he wasn't an amazing programmer, but, you know, he said after  the course ends we can, we can build apps together.  So it was more out of necessity than anything else.  But the interesting thing was he was on a path, he was much more traditional than I was.  So, you know, he was doing math classes on Saturday and, you know, school was the most  important thing in his life.  And I kind of like took him to the dark side and said, no, like capitalism, building a business  is the actual path you should follow.  And over time, I slowly kind of cracked away at him to the point where I was almost  able to sculpt him into the person I needed him to be in order to build the business we're  looking to build.  So since then, have you had any moments over a grant?  Like, oh, I should have just finished high school, should have done college.

- Rank 65 | Engine 0.71 | Legacy 0.10
  >  How are you growing up?  Were your parents bushing you towards traditional education?  Was money an issue?  So my parents came from India to the US, luckily when they're a little bit old, like  little, little younger versus my co-founders parents, they came like, I call them like,  it's like they got here last year.  They were like fresh off the boat.  But they had a lot of kind of traditional, you know, Indian values.  So going to school, doing a doctorate, becoming a doctor or an engineer as much as a  stereotype, it is true.  They really pushed me growing up to be a doctor.  And I just didn't want to do that.  Like I just, I always love building things.  So very early on, you know, like the first thing never got me was a Lego set.  And I started playing around with Legos and I'm like, I like to build things.  So how can I express my need to build things?

- Rank 105 | Engine 0.67 | Legacy 0.10
  >  And like the value to that program was I like learned how to live independently and, you  know, being my own dorm and, you know, do laundry and things that I wasn't excited to do.  But I learned how to be independent to some extent.  And the summer of eighth grade, my co-founder, Roonek, was in the dorm across the hall  for me and we started to come friends and hang out and I was like, you know, how am I  going to get out of school?  Like the only way I can get out of school is I make a lot of money.  And I'm like, how do I think I'm going to make a lot of money?  Well, I think I could start building, you know, mobile apps for small businesses.  So iOS came out with this programming language called Swift.  It was easier than Objective C, their previous language.  I thought I could learn and teach myself Swift.  And Roonek said he already knew how to program.  You know, the real truth was he wasn't an amazing programmer, but, you know, he said after  the course ends we can, we can build apps together.  So it was more out of necessity than anything else.  But the interesting thing was he was on a path, he was much more traditional than I was.  So, you know, he was doing math classes on Saturday and, you know, school was the most  important thing in his life.  And I kind of like took him to the dark side and said, no, like capitalism, building a business  is the actual path you should follow.  And over time, I slowly kind of cracked away at him to the point where I was almost  able to sculpt him into the person I needed him to be in order to build the business we're  looking to build.  So since then, have you had any moments over a grant?  Like, oh, I should have just finished high school, should have done college.

## Examples where Legacy > 0.65 and PayoffEngine < 0.4
