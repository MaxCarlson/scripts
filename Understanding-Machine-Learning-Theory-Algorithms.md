Understanding Machine Learning:
From Theory to Algorithms

© 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.

This copy is for personal use only. Not for distribution.
Do not post. Please link to:
http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

Please note: This copy is almost, but not entirely, identical to the printed version
of the book. In particular, page numbers are not identical (but section numbers are the

same).

UNDERSTANDING

MACHINE
LEARNING

_——


Understanding Machine Learning

Machine learning is one of the fastest growing areas of computer science,
with far-reaching applications. The aim of this textbook is to introduce
machine learning, and the algorithmic paradigms it offers, in a princi-
pled way. The book provides an extensive theoretical account of the
fundamental ideas underlying machine learning and the mathematical
derivations that transform these principles into practical algorithms. Fol-
lowing a presentation of the basics of the field, the book covers a wide
array of central topics that have not been addressed by previous text-
books. These include a discussion of the computational complexity of
learning and the concepts of convexity and stability; important algorith-
mic paradigms including stochastic gradient descent, neural networks,
and structured output learning; and emerging theoretical concepts such as
the PAC-Bayes approach and compression-based bounds. Designed for
an advanced undergraduate or beginning graduate course, the text makes
the fundamentals and algorithms of machine learning accessible to stu-
dents and nonexpert readers in statistics, computer science, mathematics,
and engineering.

Shai Shalev-Shwartz is an Associate Professor at the School of Computer
Science and Engineering at The Hebrew University, Israel.

Shai Ben-David is a Professor in the School of Computer Science at the
University of Waterloo, Canada.

UNDERSTANDING
MACHINE LEARNING

From Theory to
Algorithms

Shai Shalev-Shwartz

The Hebrew University, Jerusalem

Shai Ben-David

University of Waterloo, Canada

2 CAMBRIDGE
i UNIVERSITY PRESS


CAMBRIDGE

UNIVERSITY PRESS
32 Avenue of the Americas, New York, NY 10013-2473, USA

Cambridge University Press is part of the University of Cambridge.

It furthers the University’s mission by disseminating knowledge in the pursuit of
education, learning and research at the highest international levels of excellence.

www.cambridge.org
Information on this title: www.cambridge.org/9781 107057135

© Shai Shalev-Shwartz and Shai Ben-David 2014

This publication is in copyright. Subject to statutory exception

and to the provisions of relevant collective licensing agreements,

no reproduction of any part may take place without the written

permission of Cambridge University Press.

First published 2014

Printed in the United States of America

A catalog record for this publication is available from the British Library

Library of Congress Cataloging in Publication Data

ISBN 978-1-107-05713-5 Hardback

Cambridge University Press has no responsibility for the persistence or accuracy of
URLs for external or third-party Internet Web sites referred to in this publication,

and does not guarantee that any content on such Web sites is, or will remain,
accurate or appropriate.

Triple-S dedicates the book to triple-M

vii

Preface

The term machine learning refers to the automated detection of meaningful
patterns in data. In the past couple of decades it has become a common tool in
almost any task that requires information extraction from large data sets. We are
surrounded by a machine learning based technology: search engines learn how
o bring us the best results (while placing profitable ads), anti-spam software
earns to filter our email messages, and credit card transactions are secured by
a software that learns how to detect frauds. Digital cameras learn to detect
faces and intelligent personal assistance applications on smart-phones learn to
recognize voice commands. Cars are equipped with accident prevention systems
hat are built using machine learning algorithms. Machine learning is also widely
used in scientific applications such as bioinformatics, medicine, and astronomy.
One common feature of all of these applications is that, in contrast to more
raditional uses of computers, in these cases, due to the complexity of the patterns
hat need to be detected, a human programmer cannot provide an explicit, fine-
detailed specification of how such tasks should be executed. Taking example from
intelligent beings, many of our skills are acquired or refined through learning from
our experience (rather than following explicit instructions given to us). Machine

earning tools are concerned with endowing programs with the ability to “learn”
and adapt.
The first goal of this book is to provide a rigorous, yet easy to follow, intro-

duction to the main concepts underlying machine learning: What is learning?
How can a machine learn? How do we quantify the resources needed to learn a
given concept? Is learning always possible? Can we know if the learning process

succeeded or failed?

The second goal of this book is to present several key machine learning algo-

rithms. We chose to present algorithms that on one hand are successfully used
in practice and on the other hand give a wide spectrum of different learning
techniques. Additionally, we pay specific attention to algorithms appropriate for

large scale learning (a.k.a. “Big Data”), since in recent years, our world has be-

come increasingly “digitized” and the amount of data available for learning is
dramatically increasing. As a result, in many applications data is plentiful and

computation time is the main bottleneck. We therefore explicitly quantify both
the amount of data and the amount of computation time needed to learn a given
concept.

The book is divided into four parts. The first part aims at giving an initial

rigorous answer to the fundamental questions of learning. We describe a gen-

eralization of Valiant’s Probably Approximately Correct (PAC) learning model,
which is a first solid answer to the question “what is learning?”. We describe
the Empirical Risk Minimization (ERM), Structural Risk Minimization (SRM),
and Minimum Description Length (MDL) learning rules, which shows “how can
a machine learn”. We quantify the amount of data needed for learning using
the ERM, SRM, and MDL rules and show how learning might fail by deriving

viii

a “no-free-lunch” theorem. We also discuss how much computation time is re-
quired for learning. In the second part of the book we describe various learning
algorithms. For some of the algorithms, we first present a more general learning
principle, and then show how the algorithm follows the principle. While the first
wo parts of the book focus on the PAC model, the third part extends the scope
by presenting a wider variety of learning models. Finally, the last part of the
book is devoted to advanced theory.

We made an attempt to keep the book as self-contained as possible. However,
he reader is assumed to be comfortable with basic notions of probability, linear
algebra, analysis, and algorithms. The first three parts of the book are intended
or first year graduate students in computer science, engineering, mathematics, or

statistics. It can also be accessible to undergraduate students with the adequate
background. The more advanced chapters can be used by researchers intending

o gather a deeper theoretical understanding.

Acknowledgements

The book is based on Introduction to Machine Learning courses taught by Shai
Shalev-Shwartz at the Hebrew University and by Shai Ben-David at the Univer-
sity of Waterloo. The first draft of the book grew out of the lecture notes for
he course that was taught at the Hebrew University by Shai Shalev-Shwartz
during 2010-2013. We greatly appreciate the help of Ohad Shamir, who served
as a TA for the course in 2010, and of Alon Gonen, who served as a TA for the
course in 2011-2013. Ohad and Alon prepared few lecture notes and many of
he exercises. Alon, to whom we are indebted for his help throughout the entire
making of the book, has also prepared a solution manual.

We are deeply grateful for the most valuable work of Dana Rubinstein. Dana

has scientifically proofread and edited the manuscript, transforming it from
ecture-based chapters into fluent and coherent text.
Special thanks to Amit Daniely, who helped us with a careful read of the

advanced part of the book and also wrote the advanced chapter on multiclass
earnability. We are also grateful for the members of a book reading club in
Jerusalem that have carefully read and constructively criticized every line of

he manuscript. The members of the reading club are: Maya Alroy, Yossi Arje-
vani, Aharon Birnbaum, Alon Cohen, Alon Gonen, Roi Livni, Ofer Meshi, Dan
Rosenbaum, Dana Rubinstein, Shahar Somin, Alon Vinnikov, and Yoav Wald.
We would also like to thank Gal Elidan, Amir Globerson, Nika Haghtalab, Shie
Mannor, Amnon Shashua, Nati Srebro, and Ruth Urner for helpful discussions.

Shai Shalev-Shwartz, Jerusalem, Israel
Shai Ben-David, Waterloo, Canada

Part |

2

Contents

Preface

Introduction
1.1. What Is Learning?
1.2. When Do We Need Machine Learning?
1.3. Types of Learning
1.4 Relations to Other Fields
1.5. How to Read This Book
1.5.1. Possible Course Plans Based on This Book
1.6 Notation

Foundations

A Gentle Start

2.1. A Formal Model — The Statistical Learning Framework

2.2 Empirical Risk Minimization
2.2.1 Something May Go Wrong — Overfitting
2.3 Empirical Risk Minimization with Inductive Bias
2.3.1 Finite Hypothesis Classes
2.4 Exercises

A Formal Learning Model
3.1 PAC Learning
3.2. A More General Learning Model

3.2. Releasing the Realizability Assumption — Agnostic PAC

Learning
3.2.2 The Scope of Learning Problems Modeled
3.3 Summary
3.4 Bibliographic Remarks
3.5 Exercises

Learning via Uniform Convergence
4.1 Uniform Convergence Is Sufficient for Learnability
4.2 Finite Classes Are Agnostic PAC Learnable

page vii

19
19
21
22
24
25
26
27

31

33
33
35
35
36
37

ae
me oo

ag.
SONG

a
oO

ov or ot
aA BR

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.
Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

Contents

4.3
4.4
4.5

Summary
Bibliographic Remarks
Exercises

The Bias-Complexity Tradeoff

5.

5.2
5.3

5.4

a

5.8

The No-Free-Lunch Theorem

5.1.1 | No-Free-Lunch and Prior Knowledge
Error Decomposition
Summary

Bibliographic Remarks
Exercises

The VC-Dimension

6.
6.2
6.3

6.5

6.6
6.7
6.8

Infinite-Size Classes Can Be Learnable

The VC-Dimension

Examples

6.3.1 Threshold Functions

6.3.2 Intervals

6.3.3 Axis Aligned Rectangles

6.3.4 Finite Classes

6.3.5 | VC-Dimension and the Number of Parameters
The Fundamental Theorem of PAC learning

Proof of Theorem 6.7

6.5.1 | Sauer’s Lemma and the Growth Function
6.5.2 Uniform Convergence for Classes of Small Effective Size
Summary

Bibliographic remarks

Exercises

Nonuniform Learnability

7.1

7.2
7.3

7.4
7.5

7.6
7.7
7.8

Nonuniform Learnability

7.1.1 Characterizing Nonuniform Learnability
Structural Risk Minimization

Minimum Description Length and Occam’s Razor
7.3.1 Occam’s Razor

Other Notions of Learnability — Consistency
Discussing the Different Notions of Learnability
7.5.1 The No-Free-Lunch Theorem Revisited
Summary

Bibliographic Remarks

Exercises

The Runtime of Learning

8.1

Computational Complexity of Learning

oo ot
co

lor)

61
63
64
65
66
66

67
67
68
70
70
71
71
72
72
72
73
73
75
78
78
78

83
83
84
85
89
91
92
93
95
96
97
97

100
101

Part Il

10

11

8.2

8.3
8.4
8.5
8.6
8.7

Contents

8.1.1 Formal Definition*
Implementing the ERM Rule
8.2.1 Finite Classes

8.2.2 Axis Aligned Rectangles
8.2.3 Boolean Conjunctions
8.2.4 Learning 3-Term DNF
Efficiently Learnable, but Not by a Proper ERM
Hardness of Learning*
Summary

Bibliographic Remarks
Exercises

From Theory to Algorithms

Linear Predictors

9.1 Halfspaces
9.1. Linear Programming for the Class of Halfspaces
9.1.2 Perceptron for Halfspaces
9.1.3. The VC Dimension of Halfspaces
9.2 Linear Regression
9.2. Least Squares
9.2.2 Linear Regression for Polynomial Regression Tasks
9.3 Logistic Regression
9.4 Summary
9.5 Bibliographic Remarks
9.6 Exercises
Boosting
0.1 Weak Learnability
10.1.1 Efficient Implementation of ERM for Decision Stumps
0.2 AdaBoos
0.3 Linear Combinations of Base Hypotheses
10.3.1 The VC-Dimension of L(B,T)
0.4 AdaBoost for Face Recognition
0.5 Summary
0.6 Bibliographic Remarks
0.7 Exercises
Model Selection and Validation
1.1 Model Selection Using SRM
1.2 Validation

11.2.1 Hold Out Set
11.2.2 Validation for Model Selection
11.2.3 The Model-Selection Curve

xi

02
03
04
05
06
07
07
08

ooo

on

oan

20
22
23
24
25
26
28
28
28

30
31
33
34
37

SEER
NERS

ng

Sk RRB

DARA

xii

12

13

14

Contents

1.3
1.4
1.5

2.1

2.2

2.3
2.4
2.5
2.6

3.1

3.2

3.3

3.4
3.5
3.6
3.7

4.1

4.2

4.3

4.4

11.2.4 k-Fold Cross Validation
11.2.5. Train-Validation-Test Split
What to Do If Learning Fails
Summary

Exercises

Convex Learning Problems

Convexity, Lipschitzness, and Smoothness

12.1.1 Convexity

12.1.2 Lipschitzness

12.1.3 Smoothness

Convex Learning Problems

12.2.1 Learnability of Convex Learning Problems
12.2.2 Convex-Lipschitz/Smooth-Bounded Learning Problems
Surrogate Loss Functions

Summary

Bibliographic Remarks

Exercises

Regularization and Stability

Regularized Loss Minimization

13.1.1 Ridge Regression

Stable Rules Do Not Overfit

Tikhonov Regularization as a Stabilizer
13.3.1 Lipschitz Loss

13.3.2 Smooth and Nonnegative Loss
Controlling the Fitting-Stability Tradeoff
Summary

Bibliographic Remarks

Exercises

Stochastic Gradient Descent

Gradient Descent

4.1.1 Analysis of GD for Convex-Lipschitz Functions
Subgradients

4.2.1 Calculating Subgradients

4.2.2 Subgradients of Lipschitz Functions

4.2.3. Subgradient Descent

Stochastic Gradient Descent (SGD)

4.3.1 Analysis of SGD for Convex-Lipschitz-Bounded Functions
Variants

4.4.1 Adding a Projection Step

4.4.2 Variable Step Size

4.4.3 Other Averaging Techniques

71
71
72
73
74
76
77
78
80
80
81

84
85
86
88
89
90
90
91
91
93
93
94
95

15

16

17

Contents

14.4.4 Strongly Convex Functions*
4.5 Learning with SGD
14.5.1 SGD for Risk Minimization
14.5.2 Analyzing SGD for Convex-Smooth Learning Problems
14.5.3 SGD for Regularized Loss Minimization
4.6 Summary
4.7 Bibliographic Remarks
4.8 Exercises

Support Vector Machines
5.1 Margin and Hard-SVM
15.1.1 The Homogenous Case
15.1.2 The Sample Complexity of Hard-SVM

5.2 Soft-SVM and Norm Regularization
15.2.1 The Sample Complexity of Soft-SVM
15.2.2 Margin and Norm-Based Bounds versus Dimension
15.2.3 The Ramp Loss*

5.3 Optimality Conditions and “Support Vectors” *

5.4 Duality*

5.5 Implementing Soft-SVM Using SGD

5.6 Summary

5.7 Bibliographic Remarks

5.8 Exercises

Kernel Methods

6.1 Embeddings into Feature Spaces

6.2 The Kernel Trick
16.2.1 Kernels as a Way to Express Prior Knowledge
16.2.2 Characterizing Kernel Functions*

6.3 Implementing Soft-SVM with Kernels

6.4 Summary

6.5 Bibliographic Remarks

6.6 Exercises

Multiclass, Ranking, and Complex Prediction Problems
7.1 One-versus-All and All-Pairs
7.2 Linear Multiclass Predictors
17.2.1 How to Construct U
17.2.2 Cost-Sensitive Classification
17.2.3 ERM
17.2.4 Generalized Hinge Loss
17.2.5 Multiclass SVM and SGD
17.3. Structured Output Prediction
17.4 Ranking

xiii

195
196
196
198
199
200
200
201


xiv

18

19

20

Part III

21

Contents

7.6
7.7
7.8

8.1
8.2

8.3
8.4
8.5
8.6

9.1
9.2

9.4
9.6

17.4.1 Linear Predictors for Ranking

Bipartite Ranking and Multivariate Performance Measures
17.5.1 Linear Predictors for Bipartite Ranking

Summary

Bibliographic Remarks

Exercises

Decision Trees

Sample Complexity

Decision Tree Algorithms

18.2.1 Implementations of the Gain Measure

18.2.2 Pruning

18.2.3 Threshold-Based Splitting Rules for Real-Valued Features
Random Forests

Summary

Bibliographic Remarks

Exercises

Nearest Neighbor

k Nearest Neighbors

Analysis

19.2.1 A Generalization Bound for the 1-NN Rule
19.2.2 The “Curse of Dimensionality”

Efficient Implementation*

Summary

Bibliographic Remarks

Exercises

Neural Networks

20.1
20.2
20.3

20.4
20.5
20.6
20.7
20.8
20.9

Feedforward Neural Networks

Learning Neural Networks

The Expressive Power of Neural Networks
20.3.1 Geometric Intuition

The Sample Complexity of Neural Networks
The Runtime of Learning Neural Networks
SGD and Backpropagation

Summary

Bibliographic Remarks

Exercises

Additional Learning Models

Online Learning

21.1

Online Classification in the Realizable Case

240
243
245
247
247
248

260
263
264
264
264
265

268
269
270
271
273
274
276
277
281
281
282

285

287
288

22

23

24

Contents

21.1.1 Online Learnability

21.2 Online Classification in the Unrealizable Case
21.2.1 Weighted-Majority

21.3 Online Convex Optimization

21.4 The Online Perceptron Algorithm

21.5 Summary

21.6 Bibliographic Remarks

21.7 Exercises

Clustering

22.1 Linkage-Based Clustering Algorithms

22.2 k-Means and Other Cost Minimization Clusterings
22.2.1 The k-Means Algorithm

22.3 Spectral Clustering
22.3.1 Graph Cut
22.3.2 Graph Laplacian and Relaxed Graph Cuts
22.3.3 Unnormalized Spectral Clustering

22.4 Information Bottleneck*

22.5 A High Level View of Clustering

22.6 Summary

22.7 Bibliographic Remarks

22.8 Exercises

Dimensionality Reduction

23.1

23.2
23.3

23.4
23.5
23.6
23.7

Principal Component Analysis (PCA)

23.1.1 A More Efficient Solution for the Case d >> m
23.1.2 Implementation and Demonstration

Random Projections

Compressed Sensing

23.3.1 Proofs*

PCA or Compressed Sensing?

Summary

Bibliographic Remarks

Exercises

Generative Models

24.1

24.2
24.3
24.4

Maximum Likelihood Estimator

24.1.1 Maximum Likelihood Estimation for Continuous Ran-

dom Variables

24.1.2 Maximum Likelihood and Empirical Risk Minimization

24.1.3 Generalization Analysis

Naive Bayes

Linear Discriminant Analysis

Latent Variables and the EM Algorithm

xv

323
324
326
326
329
330
333
338
338
339
339

342
343

34
34
34
34
34
34

ng

a

aoa N oO

xvi Contents

24.4.1 EM as an Alternate Maximization Algorithm 350

24.4.2. EM for Mixture of Gaussians (Soft k-Means) 352

24.5 Bayesian Reasoning 353

24.6 Summary 355

24.7 Bibliographic Remarks 355

24.8 Exercises 356

25 Feature Selection and Generation 357
25.1 Feature Selection 358

25.1.1 Filters 359

25.1.2 Greedy Selection Approaches 360

25.1.3 Sparsity-Inducing Norms 363

25.2 Feature Manipulation and Normalization 365

25.2.1 Examples of Feature Transformations 367

25.3 Feature Learning 368

25.3.1 Dictionary Learning Using Auto-Encoders 368

25.4 Summary 370

25.5 Bibliographic Remarks 371

25.6 Exercises 371

Part IV Advanced Theory 373
26 Rademacher Complexities 375
26.1 The Rademacher Complexity 375

26.1.1 Rademacher Calculus 379

26.2 Rademacher Complexity of Linear Classes 382

26.3 Generalization Bounds for SVM 383

26.4 Generalization Bounds for Predictors with Low ¢; Norm 386

26.5 Bibliographic Remarks 386

27 Covering Numbers 388
27.1 Covering 388

27.1.1 Properties 388

27.2 From Covering to Rademacher Complexity via Chaining 389

27.3 Bibliographic Remarks 391

28 Proof of the Fundamental Theorem of Learning Theory 392
28.1 The Upper Bound for the Agnostic Case 392

28.2 The Lower Bound for the Agnostic Case 393

28.2.1 Showing That m(e, 6) > 0.5 log(1/(46))/e? 393

28.2.2 Showing That m(e, 1/8) > 8d/e? 395

28.3 The Upper Bound for the Realizable Case 398

28.3.1 From e-Nets to PAC Learnability 401

29

30

31

Contents

Multiclass Learnability

29.1 The Natarajan Dimension

29.2 The Multiclass Fundamental Theorem
29.2.1 On the Proof of Theorem 29.3

29.3 Calculating the Natarajan Dimension
29.3.1 One-versus-All Based Classes
29.3.2 General Multiclass-to-Binary Reductions
29.3.3 Linear Multiclass Predictors

29.4 On Good and Bad ERMs

29.5 Bibliographic Remarks

29.6 Exercises

Compression Bounds
30.1 Compression Bounds
30.2 Examples
30.2.1 Axis Aligned Rectangles
30.2.2 Halfspaces
30.2.3 Separating Polynomials
30.2.4 Separation with Margin
30.3 Bibliographic Remarks

PAC-Bayes

31.1 PAC-Bayes Bounds
31.2 Bibliographic Remarks
31.3 Exercises

Appendix A Technical Lemmas

Appendix B= Measure Concentration

Appendix C Linear Algebra

Notes
References
Index

xvii

Let ca til cardi corti corti neti cnrtill card
Se RWNNN OS

eke
NN oo

422
430
435

437
447


1.1

Introduction

The subject of this book is automated learning, or, as we will more often call
it, Machine Learning (ML). That is, we wish to program computers so that
they can “learn” from input available to them. Roughly speaking, learning is
the process of converting experience into expertise or knowledge. The input to
a learning algorithm is training data, representing experience, and the output
is some expertise, which usually takes the form of another computer program
that can perform some task. Seeking a formal-mathematical understanding of
this concept, we’ll have to be more explicit about what we mean by each of the
involved terms: What is the training data our programs will access? How can
the process of learning be automated? How can we evaluate the success of such

a process (namely, the quality of the output of a learning program)?

What Is Learning?

Let us begin by considering a couple of examples from naturally occurring ani-
mal learning. Some of the most fundamental issues in ML arise already in that
context, which we are all familiar with.

Bait Shyness — Rats Learning to Avoid Poisonous Baits: When rats encounter
food items with novel look or smell, they will first eat very small amounts, and
subsequent feeding will depend on the flavor of the food and its physiological
effect. If the food produces an ill effect, the novel food will often be associated

with the illness, and subsequently, the rats will not eat it. Clearly, there is a

learning mechanism in play here — the animal used past experience with some

food to acquire expertise in detecting the safety of this food. If past experience
with the food was negatively labeled, the animal predicts that it will also have
a negative effect when encountered in the future.

Inspired by the preceding example of successful learning, let us demonstrate a

ypical machine learning task. Suppose we would like to program a machine that

earns how to filter spam e-mails. A naive solution would be seemingly similar
o the way rats learn how to avoid poisonous baits. The machine will simply

memorize all previous e-mails that had been labeled as spam e-mails by the

human user. When a new e-mail arrives, the machine will search for it in the set

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

20

Introduction

of previous spam e-mails. If it matches one of them, it will be trashed. Otherwise,
it will be moved to the user’s inbox folder.

While the preceding “learning by memorization” approach is sometimes use-
ful, it lacks an important aspect of learning systems — the ability to label unseen
e-mail messages. A successful learner should be able to progress from individual
examples to broader generalization. This is also referred to as inductive reasoning
or inductive inference. In the bait shyness example presented previously, after
the rats encounter an example of a certain type of food, they apply their attitude
toward it on new, unseen examples of food of similar smell and taste. To achieve

generalization in the spam filtering task, the learner can scan the previously seen

e-mails, and extract a set of words whose appearance in an e-mail message is
indicative of spam. Then, when a new e-mail arrives, the machine can check

whether one of the suspicious words appears in it, and predict its label accord-

ingly. Such a system would potentially be able correctly to predict the label of
unseen e-mails.

However, inductive reasoning might lead us to false conclusions. To illustrate
this, let us consider again an example from animal learning.

Pigeon Superstition: In an experiment performed by the psychologist B. F. Skinner,

he placed a bunch of hungry pigeons in a cage. An automatic mechanism had
been attached to the cage, delivering food to the pigeons at regular intervals
with no reference whatsoever to the birds’ behavior. The hungry pigeons went
around the cage, and when food was first delivered, it found each pigeon engaged
in some activity (pecking, turning the head, etc.). The arrival of food reinforced
each bird’s specific action, and consequently, each bird tended to spend some
more time doing that very same action. That, in turn, increased the chance that
the next random food delivery would find each bird engaged in that activity
again. What results is a chain of events that reinforces the pigeons’ association
of the delivery of the food with whatever chance actions they had been perform-
ing when it was first delivered. They subsequently continue to perform these
same actions diligently.!

What distinguishes learning mechanisms that result in superstition from useful
learning? This question is crucial to the development of automated learners.
While human learners can rely on common sense to filter out random meaningless
learning conclusions, once we export the task of learning to a machine, we must
provide well defined crisp principles that will protect the program from reaching
senseless or useless conclusions. The development of such principles is a central
goal of the theory of machine learning.

What, then, made the rats’ learning more successful than that of the pigeons?

As a first step toward answering this question, let us have a closer look at the
bait shyness phenomenon in rats.

Bait Shyness revisited — rats fail to acquire conditioning between food and
electric shock or between sound and nausea: The bait shyness mechanism in

1 See: http://psychclassics.yorku.ca/Skinner/Pigeon

1.2

rats turns out to be more complex than what one may ex

1.2_When Do We Need Machine Learning?

21

pect. In experiments

carried out by Garcia (Garcia & Koelling 1996), it was demonstrated that if the
unpleasant stimulus that follows food consumption is replaced by, say, electrical

shock (rather than nausea), then no conditioning occurs.
trials in which the consumption of some food is followed by

unpleasant

Even after repeated
he administration of

electrical shock, the rats do not tend to avoid that food. Similar failure

of conditioning occurs when the characteristic of the food that implies nausea

(such as taste or smell) is replaced by a vocal signal. The rats seem

some “bui

between food and nausea can be causal, it is un

causal rela‘

sounds and nausea.

We conc!

and the pigeon superstition is the incorporation o

However, t

patterns w!
It turns

co-occurrence of noise with some food is not likely

ionship between food consumption and electrical shocks or

ude that one distinguishing feature between the bait shyness

he experiment are willing to adopt any explanation for the occurrence

he rats “know” that food cannot cause an electric shock and

of that food. The rats’ learning process is biased toward detecting some

hile ignoring other temporal correlations between events.
out that the incorporation of prior knowledge, biasing the

and prover

knowledge

of the theory of machine learning. Roughly s

to have

t in” prior knowledge telling them that, while temporal correlation
ikely that there would be a

etween

earning

prior knowledge that biases
he learning mechanism. This is also referred to as inductive bias. The pigeons in

of food.
hat the

o affect the nutritional value

kind of

earning

process, is inevitable for the success of learning algorithms (this is formally stated
as the “No-Free-Lunch theorem” in Chapter 5). The development of
ools for expressing domain expertise, translating it into a learning bias, and
quantifying the effect of such a bias on the success of learning is a central theme
peaking, the stronger the prior

(or prior assumptions) that one starts the learning process with, the

easier it is to learn from further examples. However, the stronger these prior

assumptions are, the less flexible the learning i
commitment to these assumptions. We shall

Chapter 5.

When Do We Need Machine Learning?

s — it is bound, a priori, by the

iscuss these issues explicitly in

When do we need machine learning rather than directly program our computers

to carry out the task at hand? Two aspects of a given problem may call for the

use of programs that learn and improve on the basis of their “experience”: the

problem’s complexity and the need for adaptivity.

Tasks That Are Too Complex to Program.

e Tasks Performed by Animals/Humans: There are numerous tasks that

we human beings perform routinely, yet our introspection concern-

ing how we do them is not sufficiently elaborate to extract a well

22

1.3

Introduction

defined program. Examples of such tasks include
recognition, and image understanding. In all of t
of the art machine learning programs, programs

their experience,” achieve quite satisfactory resul
to sufficiently many training examples.

driving, speech

hese tasks, state

hat “learn from
$, once exposed

e Tasks beyond Human Capabilities: Another wide family of tasks that

benefit from machine learning techniques are rela’

ed to the analy-

sis of very large and complex data sets: astronomical data, turning

medical archives into medical knowledge, weather prediction, anal-

ysis of genomic data, Web search engines, and elec

ronic commerce.

With more and more available digitally recorded data, it becomes

obvious that there are treasures of meaningful in:

ormation buried

in data archives that are way too large and too complex for humans

to make sense of. Learning to detect meaningful

atterns in large

and complex data sets is a promising domain in which the combi-

nation of programs that learn with the almost unlimited memory

capacity and ever increasing processing speed of computers opens

up new horizons.

Adaptivity. One limiting feature of programmed tools is their rigidity — once

the program has been written down and installed, it s

ays unchanged.

However, many tasks change over time or from one user to another.

Machine learning tools — programs whose behavior adapts to their input

data — offer a solution to such issues; they are, by nature, adaptive

to changes in the environment they interact with. Typical successful

applications of machine learning to such problems include programs that

decode handwritten text, where a fixed program can adapt to variations

between the handwriting of different users; spam detection programs,

adapting automatically to changes in the nature of spam e-mails; and

speech recognition programs.

Types of Learning

Learning is, of course, a very wide domain. Consequently, the

field of machine

learning has branched into several subfields dealing with different types of learn-

ing tasks. We give a rough taxonomy of learning paradigms, aiming to provide

some perspective of where the content of this book sits within
machine learning.

the wide field of

We describe four parameters along which learning paradigms can be classified.

Supervised versus Unsupervised Since learning involves an interaction be-

tween the learner and the environment, one can divide learning tasks
according to the nature of that interaction. The first distinction to note

is the difference between supervised and unsupervised learning. As an

Active

1.3 Types of Learning 23

illustrative example, consider the task of learning to detect spam e-mail
versus the task of anomaly detection. For the spam detection task, we
consider a setting in which the learner receives training e-mails for which
he label spam/not-spam is provided. On the basis of such training the
earner should figure out a rule for labeling a newly arriving e-mail mes-
sage. In contrast, for the task of anomaly detection, all the learner gets
as training is a large body of e-mail messages (with no labels) and the
earner’s task is to detect “unusual” messages.

More abstractly, viewing learning as a process of “using experience
o gain expertise,” supervised learning describes a scenario in which the
“experience,” a training example, contains significant information (say,
he spam/not-spam labels) that is missing in the unseen “test examples”

o which the learned expertise is to be applied. In this setting, the ac-
quired expertise is aimed to predict that missing information for the test
data. In such cases, we can think of the environment as a teacher that
“supervises” the learner by providing the extra information (labels). In
unsupervised learning, however, there is no distinction between training
and test data. The learner processes input data with the goal of coming
up with some summary, or compressed version of that data. Clustering
a data set into subsets of similar objets is a typical example of such a
ask.

There is also an intermediate learning setting in which, while the
raining examples contain more information than the test examples, the
earner is required to predict even more information for the test exam-
ples. For example, one may try to learn a value function that describes for
each setting of a chess board the degree by which White’s position is bet-
er than the Black’s. Yet, the only information available to the learner at
raining time is positions that occurred throughout actual chess games,
abeled by who eventually won that game. Such learning frameworks are
mainly investigated under the title of reinforcement learning.
versus Passive Learners Learning paradigms can vary by the role
played by the learner. We distinguish between “active” and “passive”
earners. An active learner interacts with the environment at training
ime, say, by posing queries or performing experiments, while a passive
earner only observes the information provided by the environment (or

he teacher) without influencing or directing it. Note that the learner of a
spam filter is usually passive — waiting for users to mark the e-mails com-
ing to them. In an active setting, one could imagine asking users to label
specific e-mails chosen by the learner, or even composed by the learner, to
enhance its understanding of what
spam is.

Helpfulness of the Teacher When one thinks about human learning, of a

baby at home or a student at school, the process often involves a helpful

teacher, who is trying to feed the learner with the information most use-

24

1.4

Introduction

‘ul for achieving the learning goal. In contrast, when a scientist learns
about nature, the environment, playing the role of the teacher, can be
est thought of as passive — apples drop, stars shine, and the rain falls
without regard to the needs of the learner. We model such learning sce-

narios by postulating that the training data (or the learner’s experience)
is generated by some random process. This is the basic building block in
he branch of “statistical learning.” Finally, learning also occurs when
he learner’s input is generated by an adversarial “teacher.” This may be
he case in the spam filtering example (if the spammer makes an effort

o mislead the spam filtering designer) or in learning to detect fraud.
One also uses an adversarial teacher model as a worst-case scenario,

when no milder setup can be safely assumed. If you can learn against an
adversarial teacher, you are guaranteed to succeed interacting any odd
eacher.
Online versus Batch Learning Protocol The last parameter we mention is
he distinction between situations in which the learner has to respond
online, throughout the learning process, and settings in which the learner
has to engage the acquired expertise only after having a chance to process
arge amounts of data. For example, a stockbroker has to make daily
decisions, based on the experience collected so far. He may become an

expert over time, but might have made costly mistakes in the process. In
contrast, in many data mining settings, the learner — the data miner —

has large amounts of training data to play with before having to output
conclusions.

In this book we shall discuss only a subset of the possible learning paradigms.
Our main focus is on supervised statistical batch learning with a passive learner
(for example, trying to learn how to generate patients’ prognoses, based on large
archives of records of patients that were independently collected and are already
labeled by the fate of the recorded patients). We shall also briefly discuss online
learning and batch unsupervised learning (in particular, clustering).

Relations to Other Fields

As an interdisciplinary field, machine learning shares common threads with the
mathematical fields of statistics, information theory, game theory, and optimiza-
tion. It is naturally a subfield of computer science, as our goal is to program
machines so that they will learn. In a sense, machine learning can be viewed as
a branch of AI (Artificial Intelligence), since, after all, the ability to turn expe-
rience into expertise or to detect meaningful patterns in complex sensory data
is a cornerstone of human (and animal) intelligence. However, one should note
that, in contrast with traditional AI, machine learning is not trying to build
automated imitation of intelligent behavior, but rather to use the strengths and

1.5

1.5 How to Read This Book 25

special abilities of computers to complement human intelligence, often perform-
ing tasks that fall way beyond human capabilities. For example, the ability to
scan and process huge databases allows machine learning programs to detect
patterns that are outside the scope of human perception.

The component of experience, or training, in machine learning often refers
o data that is randomly generated. The task of the learner is to process such
randomly generated examples toward drawing conclusions that hold for the en-
vironment from which these examples are picked. This description of machine
earning highlights its close relationship with statistics. Indeed there is a lot in
common between the two disciplines, in terms of both the goals and techniques

used. There are, however, a few significant differences of emphasis; if a doctor

comes up with the hypothesis that there is a correlation between smoking and

heart disease, it is the statistician’s role to view samples of patients and check

he validity of that hypothesis (this is the common statistical task of hypothe-

sis testing). In contrast, machine learning aims to use the data gathered from

samples of patients to come up with a description of the causes of heart disease.
The hope is that automated techniques may be able to figure out meaningful

patterns (or hypotheses) that may have been missed by the human observer.
In contrast with traditional statistics,

in machine learning in general, and
in this book in particular, algorithmic considerations play a major role. Ma-
chine learning is about the execution of learning by computers; hence algorith-

mic issues are pivotal. We develop algorithms to perform the learning tasks and
are concerned with their computational efficiency. Another difference is that
while statistics is often interested in asymptotic behavior (like the convergence
of sample-based statistical estimates as the sample sizes grow to infinity), the
theory of machine learning focuses on finite sample bounds. Namely, given the
size of available samples, machine learning theory aims to figure out the degree
of accuracy that a learner can expect on the basis of such samples.

There are further differences between these two disciplines, of which we shall

mention only one more here. While in statistics it is common to work under the

assumption of certain presubscribed data models (such as assuming the normal-
ity of data-generating distributions, or the linearity of functional dependencies),
in machine learning the emphasis is on working under a “distribution-free” set-
ting, where the learner assumes as little as possible about the nature of the
data distribution and allows the learning algorithm to figure out which models
best approximate the data-generating process. A precise discussion of this issue

requires some technical preliminaries, and we will come back to it later in the
book, and in particular in Chapter 5.

How to Read This Book

The first part of the book provides the basic theoretical principles that underlie
machine learning (ML). In a sense, this is the foundation upon which the rest

26

1.5.1

Introduction

of the book is built. This part could serve as a basis for a minicourse on the
heoretical foundations of ML.

The second part of the book introduces the most commonly used algorithmic
approaches to supervised machine learning. A subset of these chapters may also
be used for introducing machine learning in a general AI course to computer
science, Math, or engineering students.

The third part of the book extends the scope of discussion from statistical
classification to other learning models. It covers online learning, unsupervised
earning, dimensionality reduction, generative models, and feature learning.

he fourth part of the book, Advanced Theory, is geared toward readers who
have interest in research and provides the more technical mathematical tech-
niques that serve to analyze and drive forward the field of theoretical machine

earning.
The Appendixes provide some technical tools used in the book. In particular,

we list basic results from measure concentration and linear algebra.
A few sections are marked by an asterisk, which means they are addressed to
more advanced students. Each chapter is concluded with a list of exercises. A

solution manual is provided in the course Web site.

Possible Course Plans Based on This Book

A 14 Week Introduction Course for Graduate Students:

1. Chapters 2-4.
2. Chapter 9 (without the VC calculation).
3. Chapters 5-6 (without proofs).
4. Chapter 10.
5. Chapters 7, 11 (without proofs).
6. Chapters 12, 13 (with some of the easier proofs).
7. Chapter 14 (with some of the easier proofs).
8. Chapter 15.
9. Chapter 16.
10. Chapter 18.
11. Chapter 22.
12. Chapter 23 (without proofs for compressed sensing).
13. Chapter 24.
14. Chapter 25.
A 14 Week Advanced Course for Graduate Students:
1. Chapters 26, 27.
2. (continued)
3. Chapters 6, 28.
4. Chapter 7.
5. Chapter 31.


1.6

1.6 Notation 27

6. Chapter 30.
7. Chapters 12, 13.
8. Chapter 14.
9. Chapter 8.

10. Chapter 17.

11. Chapter 29.

12. Chapter 19.

13. Chapter 20.

14, Chapter 21.
Notation

Most of the notation we use throughout the book is either standard or defined
on the spot. In this section we describe our main conventions and provide a
table summarizing our notation (Table 1.1). The reader is encouraged to skip
this section and return to it if during the reading of the book some notation is
unclear.

We denote scalars and abstract objects with lowercase letters (e.g. « and A).
Often, we would like to emphasize that some object is a vector and then we
use boldface letters (e.g. x and A). The ith element of a vector x is denoted
by x;. We use uppercase letters to denote matrices, sets, and sequences. The
meaning should be clear from the context. As we will see momentarily, the input
of a learning algorithm is a sequence of training examples. We denote by z an
abstract example and by S = z1,...,2m a sequence of m examples. Historically,
S is often referred to as a training set; however, we will always assume that S' is
a sequence rather than a set. A sequence of m vectors is denoted by x1,...,Xm.-
The ith element of x; is denoted by 2x;,;.

Throughout the book, we make use of basic notions from probability. We
denote by D a distribution over some set,” for example, Z. We use the notation
z ~ D to denote that z is sampled according to D. Given a random variable
f:Z—>R, its expected value is denoted by Ez. p[f(z)]. We sometimes use the
shorthand E[f] when the dependence on z is clear from the context. For f : Z >
{true, false} we also use P..p[f(z)] to denote D({z : f(z) = true}). In the
next chapter we will also introduce the notation D’ to denote the probability

over Z™ induced by sampling (21,...,2m) where each point z; is sampled from

D independently of the other points.
In general, we have made an effort to avoid asymptotic notation. However, we

occasionally use it to clarify the main results. In particular, given f : R > Ry
and g : R + Ry, we write f = O(g) if there exist 7,a € R, such that for all
x > x we have f(x) < ag(x). We write f = o(g) if for every a > 0 there exists
2 To be mathematically precise, D should be defined over some o-algebra of subsets of Z.

The user who is not familiar with measure theory can skip the few footnotes and remarks
regarding more formal measurability definitions and assumptions.

28 Introduction

Table 1.1 Summary of notation

symbol meaning
R the set of real numbers
Rt the set of d-dimensional vectors over R
Ry the set of non-negative real numbers
the set of natural numbers
0, 0,0, w,2,0 asymptotic notation (see text)
Upootean expression) indicator function (equals 1 if expression is true and 0 o.w.)
a], = max{0,a}
n| the set {1,...,n} (for n € N)
X,V,W (column) vectors
Li, Vi, Wi the ith element of a vector
(x, v) = 4, wiv: (inner product)
|x|]2 or ||x|| = \/(x,x) (the é2 norm of x)
|x||1 =>“, |xi| (the £1 norm of x)
|x|]oo = max; |x;| (the @., norm of x)
|x||o the number of nonzero elements of x
AeRt* ad xk matrix over R
AT the transpose of A
Aj the (i, 7) element of A
xx! the d x d matrix A s.t. Ai,j = riaj (where x € R’)
X1,.-.,Xm a sequence of m vectors
Xi,j the jth element of the ith vector in the sequence
wi), ww?) the values of a vector w during an iterative algorithm
wh? the ith element of the vector w“’)
x instances domain (a set)
y labels domain (a set)
Z examples domain (a set)
H hypothesis class (a set)
LHX ZAR, loss function
D a distribution over some set (usually over Z or over 1’)
D(A) the probability of a set A C Z according to D
z~D sampling z according to D
S = 21,...,2m a sequence of m examples
S~D™ sampling S = 21,...,2m iid. according to D
P,E probability and expectation of a random variable
P.~p[f(z)] = D({z: f(z) =true}) for f : Z > {true, false}
E..p[f(2)] expectation of the random variable f : Z +R
N(p,C) Gaussian distribution with expectation ys and covariance C’
f'(2) the derivative of a function f : R— R at x
f" (2) the second derivative of a function f :R— R at x
ope) the partial derivative of a function f : R¢ > R at w w.r.t. wi
Vi(w) the gradient of a function f :R? > R at w
Of(w) the differential set of a function f : R¢ > R at w
minzec f(x) = min{f(x) : x € C} (minimal value of f over C)
maxzec f(x) = max{ f(x) : z € C} (maximal value of f over C)

argmin,¢¢ f(x) the set {a € C: f(x) = minzec f(z)}
argmax,¢c f(x) the set {2 € C: f(x) = maxzec f(z)}
log the natural logarithm


1.6 Notation 29

xq such that for all x > xo we have f(x) < ag(x). We write f = Q(g) if there
exist xo,a € Ry, such that for all « > a we have f(x) > ag(a). The notation
f = w(g) is defined analogously. The notation f = O(g) means that f = O(g)
and g = O(f). Finally, the notation f = O(g) means that there exists k € N
such that f(a) = O(g(x) log*(g(x))).

The inner product between vectors x and w is denoted by (x, w). Whenever we
do not specify the vector space we assume that it is the d-dimensional Euclidean
space and then (x, w) = an x;w;. The Euclidean (or £2) norm of a vector w is
|lw|lo = \/(w, w). We omit the subscript from the 2 norm when it is clear from
the context. We also use other ¢, norms, ||w||p = (>; |wi )'/P and in particular
|Iwl]a = 30; wi] and ||w|]o. = max; |wi|.

We use the notation minzec f(x) to denote the minimum value of the set
{f(x) : x € C}. To be mathematically more precise, we should use infyec f(x)
whenever the minimum is not achievable. However, in the context of this book

the distinction between infimum and minimum is often of little interest. Hence,

to simplify the presentation, we sometimes use the min notation even when inf
is more adequate. An analogous remark applies to max versus sup.


Part |

Foundations


2 A Gentle Start

Let us begin our mathematical analysis by showing how successful learning can be
achieved in a relatively simplified setting. Imagine you have just arrived in some
small Pacific island. You soon find out that papayas are a significant ingredient
in the local diet. However, you have never before tasted papa‘
earn how to predict whether a papaya you see in the market is tasty or not.
First, you need to decide which features of a papaya your prediction should be
based on. On the basis of your previous experience with other fruits, you decide
‘0 use two features: the papaya’s color, ranging from dark green, through orange
and red to dark brown, and the papaya’s softness, ranging from rock hard to
mushy. Your input for figuring out your prediction rule is a sample of papayas
hat you have examined for color and softness and then tasted and found out
whether they were tasty or not. Let us analyze this task as a demonstration of
he considerations involved in learning problems.

s. You have to

Our first step is to describe a formal model aimed to capture such learning
asks.

2.1 A Formal Model — The Statistical Learning Framework

e The learner’s input: In the basic statistical learning setting, the learner has
access to the following:

— Domain set: An arbitrary set, ¥. This is the set of objects that we
may wish to label. For example, in the papaya learning problem men-
tioned before, the domain set will be the set of all papayas. Usually,
these domain points will be represented by a vector of features (like
the papaya’s color and softness). We also refer to domain points as
instances and to X as instance space.

— Label set: For our current discussion, we will restrict the label set to
be a two-element set, usually {0,1} or {—1,+1}. Let Y denote our
set of possible labels. For our papayas example, let Y be {0,1}, where
1 represents being tasty and 0 stands for being not-tasty.

— Training data: S = ((x1, y1)..-(%m, Ym)) is a finite sequence of pairs in
X x y: that is, a sequence of labeled domain points. This is the input
that the learner has access to (like a set of papayas that have been

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

34 A Gentle Start

tasted and their color, softness, and tastiness). Such labeled examples
are often called training examples. We sometimes also refer to S as a
training set.

e The learner’s output: The learner is requested to output a prediction rule,
h: X + y. This function is also called a predictor, a hypothesis, or a clas-
sifier. The predictor can be used to predict the label of new domain points.
In our papayas example, it is a rule that our learner will employ to predict
whether future papayas he examines in the farmers’ market are going to

be tasty or not. We use the notation A(S) to denote the hypothesis that a

earning algorithm, A, returns upon receiving the training sequence S.

e Asimple data-generation model We now explain how the training data is

generated. First, we assume that the instances (the papayas we encounter)

are generated by some probability distribution (in this case, representing
he environment). Let us denote that probability distribution over VY by

D. It is important to note that we do not assume that the learner knows

anything about this distribution. For the type of learning tasks we discuss,

his could be any arbitrary probability distribution. As to the labels, in the
current discussion we assume that there is some “correct” labeling function,

f:&— YJ, and that y; = f(x;) for all i. This assumption will be relaxed in

he next chapter. The labeling function is unknown to the learner. In fact,

his is just what the learner is trying to figure out. In summary, each pair
in the training data S is generated by first sampling a point x; according

o D and then labeling it by f.

e Measures of success: We define the error of a classifier to be the probability

hat it does not predict the correct label on a random data point generated

by the aforementioned underlying distribution. That is, the error of h is
he probability to draw a random instance x, according to the distribution

D, such that h(x) does not equal f(x).

Formally, given a domain subset,” A C ¥, the probability distribution,

D, assigns a number, D(A), which determines how likely it is to observe a

point « € A. In many cases, we refer to A as an event and express it using
a function 7 : Y > {0,1}, namely, A = {x € X : r(x) = 1}. In that case,
we also use the notation P,.p[m(x)| to express D(A).

We define the error of a prediction rule, h: ¥ > J, to be

Lp s(h) =P (h(x) 4 f(@)] S Dw: h(a) 4 F(@)}). (2.1)

That is, the error of such h is the probability of randomly choosing an
example x for which h(x) # f(x). The subscript (D, f) indicates that the
error is measured with respect to the probability distribution D and the

1 Despite the “set” notation, S is a sequence. In particular, the same example may appear
twice in S and some algorithms can take into account the order of examples in S.
Strictly speaking, we should be more careful and require that A is a member of some
o-algebra of subsets of Y, over which D is defined. We will formally define our
measurability assumptions in the next chapter.

2

2.2

2.2.1

2.2 Empirical Risk Minimization 35

correct labeling function f. We omit this subscript when it is clear from
the context. Lip, f)(h) has several synonymous names such as the general-
ization error, the risk, or the true error of h, and we will use these names
interchangeably throughout the book. We use the letter L for the error,
since we view this error as the loss of the learner. We will later also discuss
other possible formulations of such loss.

e A note about the information available to the learner The learner is
blind to the underlying distribution D over the world and to the labeling
function f. In our papayas example, we have just arrived in a new island
and we have no clue as to how papayas are distributed and how to predict
their tastiness. The only way the learner can interact with the environment
is through observing the training set.

In the next section we describe a simple learning paradigm for the preceding
setup and analyze its performance.

Empirical Risk Minimization

As mentioned earlier, a learning algorithm receives as input a training set S,
sampled from an unknown distribution D and labeled by some target function
f, and should output a predictor hg : ¥ > Y (the subscript S emphasizes the
fact that the output predictor depends on S$). The goal of the algorithm is to
find hg that minimizes the error with respect to the unknown D and f.

Since the learner does not know what D and f are, the true error is not directly
available to the learner. A useful notion of error that can be calculated by the
learner is the training error — the error the classifier incurs over the training
sample:
det |{t € [m] : h(xa) A wi}

m

Lg(h)

(2.2)

where [m] = {1,...,m}.

The terms empirical error and empirical risk are often used interchangeably
for this error.

Since the training sample is the snapshot of the world that is available to the
learner, it makes sense to search for a solution that works well on that data.
This learning paradigm — coming up with a predictor h that minimizes Lg(h) —
is called Empirical Risk Minimization or ERM for short.

Something May Go Wrong — Overfitting
Although the ERM rule seems very natural, without being careful, this approach
may fail miserably.

To demonstrate such a failure, let us go back to the problem of learning to

36

2.3

A Gentle Start

predict the taste of a papaya on the basis of its softness and color. Consider a
sample as depicted in the following:

Assume that the probability distribution D is such that instances are distributed
uniformly within the gray square and the labeling function, f, determines the

label to be 1 if the instance is within the inner blue square, and 0) otherwise. The

area of the gray square in the picture is 2 and the area of the blue square is 1.
Consider the following predictor:
yi if He [m] st. 2, =2
hse) = 4& Um] stm (2.3)
0 otherwise.

While this predictor might seem rather artificial, in Exercise 1 we show a natural
representation of it using polynomials. Clearly, no matter what the sample is,
Lg(hg) = 0, and therefore this predictor may be chosen by an ERM algorithm (it
is one of the empirical-minimum-cost hypotheses; no classifier can have smaller
error). On the other hand, the true error of any classifier that predicts the label
1 only on a finite number of instances is, in this case, 1/2. Thus, Lp(hs) = 1/2.
We have found a predictor whose performance on the training set is excellent,
yet its performance on the true “world” is very poor. This phenomenon is called
overfitting. Intuitively, overfitting occurs when our hypothesis fits the training
data “too well” (perhaps like the everyday experience that a person who provides
a perfect detailed explanation for each of his single actions may raise suspicion).

Empirical Risk Minimization with Inductive Bias

We have just demonstrated that the ERM rule might lead to overfitting. Rather
than giving up on the ERM paradigm, we will look for ways to rectify it. We will
search for conditions under which there is a guarantee that ERM does not overfit,
namely, conditions under which when the ERM predictor has good performance
with respect to the training data, it is also highly likely to perform well over the
underlying data distribution.

A common solution is to apply the ERM learning rule over a restricted search
space. Formally, the learner should choose in advance (before seeing the data) a

set of predictors. This set is called a hypothesis class and is denoted by H. Each
h €H is a function mapping from ¥ to Y. For a given class H, and a training
sample, S, the ERM learner uses the ERM rule to choose a predictor h € H,

2.3.1

2.3 Empirical Risk Minimization with Inductive Bias 37

with the lowest possible error over S. Formally,

ERMy(S') € argmin Ls(h),
heH
where argmin stands for the set of hypotheses in H that achieve the minimum
value of Ls(h) over H. By restricting the learner to choosing a predictor from
H, we bias it toward a particular set of predictors. Such restrictions are often
called an inductive bias. Since the choice of such a restriction is determined
before the learner sees the training data, it should ideally be based on some
prior knowledge about the problem to be learned. For example, for the papaya
taste prediction problem we may choose the class H to be the set of predictors
that are determined by axis aligned rectangles (in the space determined by the

color and softness coordinates). We will later show that ERMy over this class is
guaranteed not to overfit. On the other hand, the example of overfitting that we
have seen previously, demonstrates that choosing H. to be a class of predictors
that includes all functions that assign the value 1 to a finite set of domain points
does not suffice to guarantee that ERM, will not overfit.
A fundamental question in learning theory is, over which hypothesis classes

ERM, learning will not result in overfitting. We will study this question later

in the book.
Intuitively, choosing a more restricted hypothesis class better protects us

against overfitting but at the same time might cause us a stronger inductive

bias. We will get back to this fundamental tradeoff later.

Finite Hypothesis Classes

The simplest type of restriction on a class is imposing an upper bound on its size
(that is, the number of predictors h in 1). In this section, we show that if H is
a finite class then ERM, will not overfit, provided it is based on a sufficiently
arge training sample (this size requirement will depend on the size of 1).

Limiting the learner to prediction rules within some finite hypothesis class may
be considered as a reasonably mild restriction. For example, H. can be the set of
all predictors that can be implemented by a C++ program written in at most
0° bits of code. In our papayas example, we mentioned previously the class of
axis aligned rectangles. While this is an infinite class, if we discretize the repre-
sentation of real numbers, say, by using a 64 bits floating-point representation,
he hypothesis class becomes a finite class.

Let us now analyze the performance of the ERMy, learning rule assuming that
H is a finite class. For a training sample, S, labeled according to some f : ¥ > Y,

et hg denote a result of applying ERMy to S, namely,

hs € argmin Ls(h). (2.4)
heH
In this chapter, we make the following simplifying assumption (which will be
relaxed in the next chapter).

38

A Gentle Start

DEFINITION 2.1 (The Realizability Assumption) There

exists h* € H s.t.

Ly, p)(h*) = 0. Note that this assumption implies that with probability 1 over

random samples, 5, where the instances of S are sampled
are labeled by f, we have Lg(h*) = 0.

The realizability assumption implies that for every ERM

according to D and

hypothesis we have

that® Ls(hg) = 0. However, we are interested in the true risk of hs, Lip, sy(hs),

rather than its empirical risk.

Clearly, any guarantee on the error with respect to the underlying distribution,

D, for an algorithm that has access only to a sample S should depend on the

relationship between D and S. The common assumption in statistical machine

learning is that the training sample S' is generated by samp

distribution D independently of each other. Formally,

ling points from the

e The i.i.d. assumption: The examples in the training set are independently

and identically distributed (i.i.d.) according to the distribution D. That is,

every x; in S is freshly sampled according to D and then labeled according

to the labeling function, f. We denote this assumption by S ~ D™ where

m is the size of S, and D™ denotes the probability over m-tuples induced

by applying D to pick each element of the tuple independently of the other

members of the tuple.

Intuitively, the training set S is a window through which the learner

gets partial information about the distribution D over the world and the

labeling function, f. The larger the sample gets, the

more likely it is to

reflect more accurately the distribution and labeling used to generate it.

Since Lp, f)(hs) depends on the training set, 5, and that training set is picked

by a random process, there is randomness in the choice
and, consequently, in the ris Lipp) (hs). Formally, we say

asting example, there is always some (small) chance tha’

have happened to taste were not tasty, in spite of the fact

distribution of papapyas in the island). We will therefore ad

he probability of getting a nonrepresentative sample by 4,

confidence parameter of our prediction.

of the predictor hg
that it is a random

variable. It is not realistic to expect that with full certainty S will suffice to
direct the learner toward a good classifier (from the point of view of D), as
here is always some probability that the sampled training data happens to
be very nonrepresentative of the underlying D. If we go back to the papaya

all the papayas we
hat, say, 70% of the

papayas in our island are tasty. In such a case, ERMy,() may be the constant
unction that labels every papaya as “not tasty” (and has 70% error on the true

dress the probability

o sample a training set for which Lip, py (hs) is not too large. Usually, we denote

and call (1 — 6) the

On top of that, since we cannot guarantee perfect label prediction, we intro-

duce another parameter for the quality of prediction, the

accuracy parameter,

3 Mathematically speaking, this holds with probability 1. To simplify the presentation, we

sometimes omit the “with probability 1” specifier.

2.3 Empirical Risk Minimization with Inductive Bias 39

commonly denoted by ¢. We interpret the event Lip, p)(hs) > € as a failure of the
learner, while if Lyp, p)(h sg) <€ we view the output of the algorithm as an approx-
imately correct predictor. Therefore (fixing some labeling function f : ¥ — )),
we are interested in upper bounding the probability to sample m-tuple of in-
stances that will lead to failure of the learner. Formally, let S|, = (%1,-.-,%m)
be the instances of the training set. We would like to upper bound

D"({Slx : Low,p)(hs) > €})-
Let Hg be the set of “bad” hypotheses, that is,
Hp = {h eH: Lyp,p)(h) > ¢}-
In addition, let
M = {S| : dh € Hg, Ls(h) = 0}

be the set of misleading samples: Namely, for every S|, € M, there is a “bad”
hypothesis, h € Hg, that looks like a “good” hypothesis on S|,,. Now, recall that
we would like to bound the probability of the event Lip,,)(hs) > €. But, since
the realizability assumption implies that Ls(hs) = 0, it follows that the event
L(p,s)(hs) > € can only happen if for some h € Hg we have Ls(h) = 0. In

other words, this event will only happen if our sample is in the set of misleading
samples, 1M. Formally, we have shown that

{Sle:Lip,p(hs) > ef} CM.
Note that we can rewrite M as

M= VU {s

heHp

a : Ds(h) = 0}. (2.5)

Hence,

DM ({Sle : Lew, p(hs) > eh) S D™(M) =D" (Unens {Sle : Ls(h) = 0}).

(2.6)

Next, we upper bound the right-hand side of the preceding equation using the
union bound — a basic property of probabilities.
LEMMA 2.2 (Union Bound) For any two sets A,B and a distribution D we
have

D(AUB) < D(A) + D(B).
Applying the union bound to the right-hand side of Equation (2.6) yields

D"({Sl2:Lew,p(hs) >) < SO DMS

heHs

2 : Lg(h) = 0}). (2.7)

Next, let us bound each summand of the right-hand side of the preceding in-
equality. Fix some “bad” hypothesis h € Hg. The event Ls(h) = 0 is equivalent

40 A Gentle Start

to the event Vi, h(a;) = f(a;). Since the examples in the training set are sampled
iid. we get that

D"({Sln : Ls(h) =0}) =D" ({S|x : Vi, h(wi) = f(as)})

m

= [[ Pllai : hei) = f(@i)})- (2.8)
i=l

For each individual sampling of an element of the training set we have
D({xi : h(i) = yi}) =1—Lewp(h) <1 -«,

where the last inequality follows from the fact that h € Hg. Combining the

previous equation with Equation (2.8) and using the inequality 1 — « < e~* we
obtain that for every h € Hp,
D"({S|2 : Ls(h) = 0}) <1 -6)™<e™. (2.9)

Combining this equation with Equation (2.7) we conclude that

D™({5

2: Lp,p(hs) > e}) < \Hele™ < |Hle*™.

A graphical illustration which explains how we used the union bound is given in
Figure 2.1.

Figure 2.1 Each point in the large circle represents a possible m-tuple of instances.
Each colored oval represents the set of “misleading” m-tuple of instances for some
“bad” predictor h € Hg. The ERM can potentially overfit whenever it gets a
misleading training set S. That is, for some h € Hg we have Lg(h) = 0.

Equation (2.9) guarantees that for each individual bad hypothesis, h € Hg, at most
(1 — «)™-fraction of the training sets would be misleading. In particular, the larger m
is, the smaller each of these colored ovals becomes. The union bound formalizes the
fact that the area representing the training sets that are misleading with respect to
some h € Hz (that is, the training sets in M) is at most the sum of the areas of the
colored ovals. Therefore, it is bounded by |Hs| times the maximum size of a colored
oval. Any sample S outside the colored ovals cannot cause the ERM rule to overfit.

COROLLARY 2.3 Let H be a finite hypothesis class. Let 6 € (0,1) and e > 0

2.4

2.4 Exercises 41

and let m be an integer that satisfies

> WoallH/a),

€
Then, for any labeling function, f, and for any distribution, D, for which the
realizability assumption holds (that is, for some h € H, Lyp,py(h) = 0), with
probability of at least 1—6 over the choice of an i.i.d. sample S of size m, we
have that for every ERM hypothesis, hg, it holds that

Lop plas) <e.

The preceeding corollary tells us that for a sufficiently large m, the ERM rule
over a finite hypothesis class will be probably (with confidence 1—6) approximately
(up to an error of €) correct. In the next chapter we formally define the model
of Probably Approximately Correct (PAC) learning.

Exercises

1. Overfitting of polynomial matching: We have shown that the predictor
defined in Equation (2.3) leads to overfitting. While this predictor seems to
be very unnatural, the goal of this exercise is to show that it can be described
as a thresholded polynomial. That is, show that given a training set S =
{(xi, f(xi)) }@2, C (R¢ x {0,1})™, there exists a polynomial ps such that
hg(x) = 1 if and only if ps(x) > 0, where hg is as defined in Equation (2.3).
It follows that learning the class of all thresholded polynomials using the ERM

rule may lead to overfitting.

2. Let H be a class of binary classifiers over a domain 4. Let D be an unknown
distribution over 4’, and let f be the target hypothesis in H. Fix some h € H.
Show that the expected value of Ls(h) over the choice of S|, equals Lip, p)(),
namely,

E_ [Ls(h)|=L h).

siepml s(h)] = Li, p)(h)

3. Axis aligned rectangles: An axis aligned rectangle classifier in the plane
is a classifier that assigns the value 1 to a point if and only if it is inside a
certain rectangle. Formally, given real numbers a1 < bi,a2 < be, define the

classifier h(a,,b,,a2,b2) bY

1 ifa, <2, < by and ag < xq < bo

Pay bi ,a2,b2) (152) = { (2.10)

0 otherwise
The class of all axis aligned rectangles in the plane is defined as
Hove = {May,b1,a2,b2) 2% <br, and ag < by}.

Note that this is an infinite size hypothesis class. Throughout this exercise we
rely on the realizability assumption.

42 A Gentle Start

1. Let A be the algorithm that returns the smallest rectangle enclosing all
ositive examples in the training set. Show that A is an ERM.
2. Show that if A receives a training set of size > Ales(4/4) then, with proba-
ility of at least 1 — 6 it returns a hypothesis with error of at most e.

Hint: Fix some distribution D over 1, let R* = R(aj, bj, a3, b3) be the rect-
angle that generates the labels, and let f be the corresponding hypothesis.
Let a; > aj be a number such that the probability mass (with respect
o D) of the rectangle Ry = R(aj,a),a3,b3) is exactly €/4. Similarly, let
b1, @2,b2 be numbers such that the probability masses of the rectangles
Ry = R(b1, bj, a3, 05), Rg = R(aj, bj, a3, a2), Ry = Raj, bt, be, 3) are all
exactly €/4. Let R(S) be the rectangle returned by A. See illustration in

Figure 2.2.

R(SI

ef

Figure 2.2 Axis aligned rectangles.

e Show that R(S') C R*.

e Show that if $ contains (positive) examples in all of the rectangles
R,, Ro, R3,R4, then the hypothesis returned by A has error of at
most e€.

e For each i € {1,...,4}, upper bound the probability that S does not
contain an example from Rj.

e Use the union bound to conclude the argument.

3. Repeat the previous question for the class of axis aligned rectangles in R¢.
4. Show that the runtime of applying the algorithm A mentioned earlier is
polynomial in d,1/e, and in log(1/6).

3

3.1

A Formal Learning Model

In this chapter we define our main formal learning model — the PAC learning
model and its extensions. We will consider other notions of learnability in Chap-
ter 7.

PAC Learning

In the previous chapter we have shown that for a finite hypothesis class, if the
ERM rule with respect to that class is applied on a sufficiently large training
sample (whose size is independent of the underlying distribution or labeling
function) then the output hypothesis will be probably approximately correct.
More generally, we now define Probably Approximately Correct (PAC) learning.

DEFINITION 3.1 (PAC Learnability) A hypothesis class H is PAC learnable
if there exist a function my : (0,1)? > N and a learning algorithm with the
following property: For every ¢,6 € (0,1), for every distribution D over 7, and
for every labeling function f : Y — {0,1}, if the realizable assumption holds
with respect to H,D,f, then when running the learning algorithm on m >
my(e, 6) iid. examples generated by D and labeled by f, the algorithm returns
a hypothesis h such that, with probability of at least 1 — 6 (over the choice of
the examples), Lip,p)(h) < €.

The definition of Probably Approximately Correct learnability contains two
approximation parameters. The accuracy parameter € determines how far the
output classifier can be from the optimal one (this corresponds to the “approx-
imately correct”), and a confidence parameter 6 indicating how likely the clas-
sifier is to meet that accuracy requirement (corresponds to the “probably” part
of “PAC”). Under the data access model that we are investigating, these ap-
proximations are inevitable. Since the training set is randomly generated, there
may always be a small chance that it will happen to be noninformative (for ex-
ample, there is always some chance that the training set will contain only one
domain point, sampled over and over again). Furthermore, even when we are

lucky enough to get a training sample that does faithfully represent D, because
it is just a finite sample, there may always be some fine details of D that it fails

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

44

3.2

A Formal Learning Model

to reflect. Our accuracy parameter, ¢, allows “forgiving” the learner’s classifier
for making minor errors.

Sample Complexity

The function mz : (0,1)? + N determines the sample complexity of learning H:
that is, how many examples are required to guarantee a probably approximately
correct solution. The sample complexity is a function of the accuracy (e) and
confidence (6) parameters. It also depends on properties of the hypothesis class
H — for example, for a finite class we showed that the sample complexity depends
on log the size of H.

Note that if H is PAC learnable, there are many functions my that satisfy the
requirements given in the definition of PAC learnability. Therefore, to be precise,
we will define the sample complexity of learning H to be the “minimal function,”
in the sense that for any €,6, m(e,6) is the minimal integer that satisfies the
requirements of PAC learning with accuracy € and confidence 6.

Let us now recall the conclusion of the analysis of finite hypothesis classes
from the previous chapter. It can be rephrased as stating:

COROLLARY 3.2 Every finite hypothesis class is PAC learnable with sample
complexity
log 6
my(e,d) < je).
€

There are infinite classes that are learnable as well (see, for example, Exer-
cise 3). Later on we will show that what determines the PAC learnability of
a class is not its finiteness but rather a combinatorial measure called the VC
dimension.

A More General Learning Model

The model we have just described can be readily generalized, so that it can be
made relevant to a wider scope of learning tasks. We consider generalizations in
two aspects:

Removing the Realizability Assumption

We have required that the learning algorithm succeeds on a pair of data distri-
bution D and labeling function f provided that the realizability assumption is
met. For practical learning tasks, this assumption may be too strong (can we
really guarantee that there is a rectangle in the color-hardness space that fully
determines which papayas are tasty”). In the next subsection, we will describe
the agnostic PAC model in which this realizability assumption is waived.

3.2.1

3.2 A More General Learning Model 45

Learning Problems beyond Binary Classification

The learning task that we have been discussing so far has to do with predicting a
binary label to a given example (like being tasty or not). However, many learning
tasks take a different form. For example, one may wish to predict a real valued
number (say, the temperature at 9:00 p.m. tomorrow) or a label picked from
a finite set of labels (like the topic of the main story in tomorrow’s paper). It
turns out that our analysis of learning can be readily extended to such and many
other scenarios by allowing a variety of loss functions. We shall discuss that in
Section 3.2.2 later.

Releasing the Realizability Assumption — Agnostic PAC Learning
A More Realistic Model for the Data-Generating Distribution

Recall that the realizability assumption requires that there exists h* € H such
that P,.p[h*(x) = f(x)] = 1. In many practical problems this assumption does
not hold. Furthermore, it is maybe more realistic not to assume that the labels
are fully determined by the features we measure on input elements (in the case of
the papayas, it is plausible that two papayas of the same color and softness will
have different taste). In the following, we relax the realizability assumption by
replacing the “target labeling function” with a more flexible notion, a data-labels
generating distribution.

Formally, from now on, let D be a probability distribution over ¥ x Y, where,

as before, ¥ is our domain set and J is a set of labels (usually we will consider
Y = {0,1}). That is, D is a joint distribution over domain points and labels. One
can view such a distribution as being composed of two parts: a distribution D,
over unlabeled domain points (sometimes called the marginal distribution) and

a conditional probability over labels for each domain point, D((x, y)|x). In the

papaya example, D,, determines the probability of encountering a papaya whose
color and hardness fall in some color-hardness values domain, and the conditional
probability is the probability that a papaya with color and hardness represented
by x is tasty. Indeed, such modeling allows for two papayas that share the same

color and hardness to belong to different taste categories.

The empirical and the True Error Revised
For a probability distribution, D, over ¥ x Y, one can measure how likely h is

to make an error when labeled points are randomly drawn according to D. We
redefine the true error (or risk) of a prediction rule h to be

def def 9
Lo(h) SP ihe) Au] & D(lew) she) Avy). Ba)
We would like to find a predictor, h, for which that error will be minimized.
However, the learner does not know the data generating D. What the learner
does have access to is the training data, S. The definition of the empirical risk

46

A Formal Learning Model

remains the same as before, namely,

Ls(h) det |{i € [m] : h(a) # vid

m

Given S, a learner can compute Lg(h) for any function h : X — {0,1}. Note
that Ls(h) = Lp(uniform over s)(h)-

The Goal
We wish to find some hypothesis, h : ¥ — JY, that (probably approximately)
minimizes the true risk, Lp(h).

The Bayes Optimal Predictor.
Given any probability distribution D over Y x {0,1}, the best label predicting
function from ¥ to {0,1} will be

fo(x) = {i if Ply = 12] > 1/2

0 otherwise

It is easy to verify (see Exercise 7) that for every probability distribution D,
he Bayes optimal predictor fp is optimal, in the sense that no other classifier,
g: & — {0,1} has a lower error. That is, for every classifier g, Lp(fp) < Lp(g).
Unfortunately, since we do not know D, we cannot utilize this optimal predictor
fp. What the learner does have access to is the training sample. We can now
present the formal definition of agnostic PAC learnability, which is a natural
extension of the definition of PAC learnability to the more realistic, nonrealizable,
earning setup we have just discussed.

Clearly, we cannot hope that the learning algorithm will find a hypothesis
whose error is smaller than the minimal possible error, that of the Bayes predic-
or.

Furthermore, as we shall prove later, once we make no prior assumptions
about the data-generating distribution, no algorithm can be guaranteed to find
a predictor that is as good as the Bayes optimal one. Instead, we require that
he learning algorithm will find a predictor whose error is not much larger than
he best possible error of a predictor in some given benchmark hypothesis class.
Of course, the strength of such a requirement depends on the choice of that

hypothesis class.

DEFINITION 3.3 (Agnostic PAC Learnability) A hypothesis class H is agnostic
PAC learnable if there exist a function my : (0,1)? > N and a learning algorithm
with the following property: For every €,6 € (0,1) and for every distribution D

over ¥ x Y, when running the learning algorithm on m > my (e, 6) i.i.d. examples

generated by D, the algorithm returns a hypothesis h such that, with probability
of at least 1 — 6 (over the choice of the m training examples),

< + Ul
Lp(h) < ain Lp(h’) +e.

3.2.2

3.2 A More General Learning Model 47

Clearly, if the realizability assumption holds, agnostic PAC learning provides

the same guarantee as PAC learning. In that sense, agnostic PAC learning gener-

alizes the definition of PAC learning. When the realizability assumption does not

hold, no learner can guarantee an arbitrarily small error. Nevertheless, under the

definition of agnostic PAC learning, a learner can still declare success if its error

is not much larger than the best error achievable by a predictor from the class H.

This is in contrast to PAC learning, in which the learner is required to achieve

a small error in absolute terms and not relative to the best error achievable by

the hypothesis class.

The Scope of Learning Problems Modeled

We next extend our model so that it can be applied to a wide variety of learning

tasks. Let us consider some examples of different learning tasks.

Multiclass Classification Our classification does not have to be binary.

Take, for example, the task of document classification: We wish to design a
program that will be able to classify given documents according to topics
(e.g., news, sports, biology, medicine). A learning algorithm for such a task
will have access to examples of correctly classified documents and, on the
basis of these examples, should output a program that can take as input a

cation for that document. Here,

new document and output a topic classi
he domain set is the set of all potential documents. Once again, we would

of different key words in the document, as well as other possibly relevant

usually represent documents by a set of features that could include counts
eatures like the size of the document or its origin. The label set in this task
will be the set of possible document topics (so Y will be some large finite

set). Once we determine our domain and label sets, the other components

of our framework look exactly the same as in the papaya tasting example;

Our training sample will be a finite sequence of (feature vector, label) pairs,

the learner’s output will be a function from the domain set to the label set,

and, finally, for our measure of success, we can use the probability, over

(document, topic) pairs, of the event that our predictor suggests a wrong
label.

e Regression In this task, one wishes to find some simple pattern in the data —

a functional relationship between the ¥ and Y components of the data. For
example, one wishes to find a linear function that best predicts a baby’s
birth weight on the basis of ultrasound measures of his head circumference,
abdominal circumference, and femur length. Here, our domain set V is some
and the set of “labels,”
Y, is the the set of real numbers (the weight in grams). In this context,

subset of R? (the three ultrasound measurements

it is more adequate to call Y the target set. Our training data as well as
the learner’s output are as before (a finite sequence of (x,y) pairs, and

a function from ¥ to ) respectively). However, our measure of success is

48 A Formal Learning Model

different. We may evaluate the quality of a hypothesis function, h: ¥ > y,
by the expected square difference between the true labels and their predicted
values, namely,
Lp(h)  E _(h(x) — y)?. (3.2)
(@,y)~D
To accommodate a wide range of learning tasks we generalize our formalism
of the measure of success as follows:

Generalized Loss Functions

Given any set H (that plays the role of our hypotheses, or models) and some
domain Z let ¢ be any function from H x Z to the set of nonnegative real numbers,
L:HxZOR,.

We call such functions loss functions.

Note that for prediction problems, we have that Z = XY x Y. However, our
notion of the loss function is generalized beyond prediction tasks, and therefore
it allows Z to be any domain of examples (for instance, in unsupervised learning
tasks such as the one described in Chapter 22, Z is not a product of an instance
domain and a label domain).

We now define the risk function to be the expected loss of a classifier, h € H,
with respect to a probability distribution D over Z, namely,

Lp(h) E leh, 2)]- (3.3)

an

That is, we consider the expectation of the loss of h over objects z picked ran-

domly according to D. Similarly, we define the empirical risk to be the expected

loss over a given sample S = (21,...,2m) € Z'™, namely,
ae 1
Ls(h) & m allt zi). (3.4)

The loss functions used in the preceding examples of classification and regres-
sion tasks are as follows:

e 0-1 loss: Here, our random variable z ranges over the set of pairs ¥ x Y and
the loss function is

0 if A(z)=y

1 if h(x) Ay

This loss function is used in binary or multiclass classification problems.

lo-r(h,(e,y)) & {

One should note that, for a random variable, a, taking the values {0, 1},
Egxpla] = Paxp[a = 1]. Consequently, for this loss function, the defini-
tions of Lp(h) given in Equation (3.3) and Equation (3.1) coincide.

e Square Loss: Here, our random variable z ranges over the set of pairs ¥ x Y
and the loss function is

def

bog(h, (a,y)) = (h(x) -— y)?.

3.3

3.3. Summary 49

This loss function is used in regression problems.

We will later see more examples of useful instantiations of loss functions.

To summarize, we formally define agnostic PAC learnability for general loss
functions.

DEFINITION 3.4 (Agnostic PAC Learnability for General Loss Functions) A
hypothesis class H is agnostic PAC learnable with respect to a set Z and a
loss function 2: H x Z > R4, if there exist a function my : (0,1)? ~ N
and a learning algorithm with the following property: For every ¢,5 € (0,1)
and for every distribution D over Z, when running the learning algorithm on
m > my(e,6) iid. examples generated by D, the algorithm returns h € H
such that, with probability of at least 1 — 6 (over the choice of the m training
examples),

< mi '
Lp(h) < min Lp(h') +e,

where Lp(h) = E,~p[¢(h, z)]-

Remark 3.1 (A Note About Measurability*) In the aforementioned definition,
for every h € H, we view the function é(h,-) : Z + R, as a random variable and
define Lp(h) to be the expected value of this random variable. For that, we need
to require that the function ¢(h, -) is measurable. Formally, we assume that there
is a o-algebra of subsets of Z, over which the probability D is defined, and that
the preimage of every initial segment in R, is in this o-algebra. In the specific

case of binary classification with the 0—1 loss, the o-algebra is over ¥ x {0,1}

and our assumption on £ is equivalent to the assumption that for every h, the
set {(x, h(x)) : « € 4X} is in the o-algebra.

Remark 3.2 (Proper versus Representation-Independent Learning*) In the pre-

ceding definition, we required that the algorithm will return a hypothesis from
H. In some situations, H. is a subset of a set H’, and the loss function can be
naturally extended to be a function from H’ x Z to the reals. In this case, we
may allow the algorithm to return a hypothesis h’ € H’, as long as it satisfies
the requirement Lp(h’) < minney Lp(h) + €. Allowing the algorithm to output
a hypothesis from H’ is called representation independent learning, while proper
learning occurs when the algorithm must output a hypothesis from H. Represen-
tation independent learning is sometimes called “improper learning,” although
there is nothing improper in representation independent learning.

Summary

In this chapter we defined our main formal learning model — PAC learning. The
basic model relies on the realizability assumption, while the agnostic variant does

50

3.4

3.5

A_Formal Learning Model

not impose any restrictions on the underlying distribution over the examples. We
also generalized the PAC model to arbitrary loss functions. We will sometimes
refer to the most general model simply as PAC learning, omitting the “agnostic”
prefix and letting the reader infer what the underlying loss function is from the
context. When we would like to emphasize that we are dealing with the original
PAC setting we mention that the realizability assumption holds. In Chapter 7
we will discuss other notions of learnability.

Bibliographic Remarks

Our most general definition of agnostic PAC learning with general loss func-
tions follows the works of Vladimir Vapnik and Alexey Chervonenkis (Vapnik &
Chervonenkis 1971). In particular, we follow Vapnik’s general setting of learning
(Vapnik 1982, Vapnik 1992, Vapnik 1995, Vapnik 1998).

PAC learning was introduced by Valiant (1984). Valiant was named the winner
of the 2010 Turing Award for the introduction of the PAC model. Valiant’s
definition requires that the sample complexity will be polynomial in 1/e and
in 1/6, as well as in the representation size of hypotheses in the class (see also
Kearns & Vazirani (1994)). As we will see in Chapter 6, if a problem is at all PAC

learnable then the sample complexity depends polynomially on 1/e and log(1/6).

Valiant’s definition also requires that the runtime of the learning algorithm will
be polynomial in these quantities. In contrast, we chose to distinguish between
the statistical aspect of learning and the computational aspect of learning. We

will elaborate on the computational aspect later on in Chapter 8, where we
introduce the full PAC learning model of Valiant. For expository reasons, we

use the term PAC learning even when we ignore the runtime aspect of learning.

Finally, the formalization of agnostic PAC learning is due to Haussler (1992).

Exercises

1. Monotonicity of Sample Complexity: Let H be a hypothesis class for a
binary classification task. Suppose that H is PAC learnable and its sample
complexity is given by m,(-,-). Show that my, is monotonically nonincreasing
in each of its parameters. That is, show that given 6 € (0,1), and given 0 <
€1 < €2 < 1, we have that my(e1,6) > my(e2,5). Similarly, show that given
€ € (0,1), and given 0 < 6; < 2 < 1, we have that my(e, 61) > myx(e, 52).

2. Let X be a discrete domain, and let Hgingleton = {hz : 2 € V}U {h7}, where
for each z € X, hz is the function defined by hz(a) = 1 if = z and hz(x) = 0
if x # z. h~ is simply the all-negative hypothesis, namely, Vx € X, h~ (x) = 0.
The realizability assumption here implies that the true hypothesis f labels
negatively all examples in the domain, perhaps except one.

on

3.5 Exercises 51

. Describe an algorithm that implements the ERM rule for learning Hgingteton
in the realizable setup.

2. Show that Hgingleton is PAC learnable. Provide an upper bound on the

sample complexity.

. Let X = R?, Y = {0,1}, and let H be the class of concentric circles in the

lane, that is, H = {h, :r € Ry}, where h,(x) = lyjai<,j. Prove that H is
PAC learnable (assume realizability), and its sample complexity is bounded
ry

my(e,d) < eo] :

n this question, we study the hypothesis class of Boolean conjunctions defined
as follows. The instance space is ¥ = {0, 1}4 and the label set is Y = {0,1}. A
iteral over the variables 11,...,2q is a simple Boolean function that takes the
‘orm f(x) = 2;, for some i € [d], or f(x) = 1—«; for some i € [d]. We use the
notation Z; as a shorthand for 1—2;. A conjunction is any product of literals.
n Boolean logic, the product is denoted using the A sign. For example, the

‘unction h(x) = x1 - (1 — 22) is written as x A Z2.

We consider the hypothesis class of all conjunctions of literals over the d
variables. The empty conjunction is interpreted as the all-positive hypothesis
(namely, the function that returns h(x) = 1 for all x). The conjunction 7 AZ1
(and similarly any conjunction involving a literal and its negation) is allowed
and interpreted as the all-negative hypothesis (namely, the conjunction that
returns h(x) = 0 for all x). We assume realizability: Namely, we assume
that there exists a Boolean conjunction that generates the labels. Thus, each
example (x, y) € Y x Y consists of an assignment to the d Boolean variables
X1,.--,Xq, and its truth value (0 for false and 1 for true).

For instance, let d = 3 and suppose that the true conjunction is 71 A £2.

Then, the training set S might contain the following instances:
((1,1,1),0), ((1,0, 1), 1), ((0, 1, 0),0)((1,0,0), 1).

Prove that the hypothesis class of all conjunctions over d variables is
PAC learnable and bound its sample complexity. Propose an algorithm that
implements the ERM rule, whose runtime is polynomial in d-m.

. Let & be a domain and let D,,D2,...,D, be a sequence of distributions

over X. Let H be a finite class of binary classifiers over ¥ and let f € H.
Suppose we are getting a sample S' of m examples, such that the instances are

independent but are not identically distributed; the ith instance is sampled
from D; and then y; is set to be f(x;). Let D,, denote the average, that is,

Dm = (Di +++: +Dm)/m.

Fix an accuracy parameter € € (0,1). Show that

P[ah eH st. Lop,, p(h) > € and Lys, py(h) = 0] < |Hle*".

52

A_Formal Learning Model

Hint: Use the geometric-arithmetic mean inequality.

6. Let H be a hypothesis class of binary classifiers. Show that if H is agnostic
PAC learnable, then H is PAC learnable as well. Furthermore, if A is a suc-
cessful agnostic PAC learner for 1, then A is also a successful PAC learner

for H.

7. (*) The Bayes optimal predictor: Show that for every probability distri-

bution D, the Bayes optimal predictor fp is optimal, in the sense that for

every classifier g from ¥ to {0,1}, Lp(fp) < L(g).

8. (*) We say that a learning algorithm A is better than B with respect to some

probability distribution, D, if

Lp(A(S)) < Lp(B(S))
for all samples S € (4 x {0,1})". We say that a learning algorithm A is better
than B, if it is better than B with respect to all probability distributions D

over X x {0,1}.
. A probabilistic label predictor is a function that assigns to every domain

oint x a probability value, h(x) € [0, 1], that determines the probability of
redicting the label 1. That is, given such an h and an input, x, the label for
x is predicted by tossing a coin with bias h(z) toward Heads and predicting
iff the coin comes up Heads. Formally, we define a probabilistic label
redictor as a function, h : ¥ — [0,1]. The loss of such h on an example
(x,y) is defined to be |h(x) — y|, which is exactly the probability that the
rediction of h will not be equal to y. Note that if h is deterministic, that

is, returns values in {0,1}, then |A(ax) — y| = In(ey4y)-
Prove that for every data-generating distribution D over XY x {0,1}, the

Bayes optimal predictor has the smallest risk (w.r.t. the loss function
Lh, (x, y)) = |h(x)—y|, among all possible label predictors, including prob-
abilistic ones).
2. Let Y be a domain and {0,1} be a set of labels. Prove that for every

distribution D over ¥ x {0,1}, there exist a learning algorithm Ap that is
etter than any other learning algorithm with respect to D.
3. Prove that for every learning algorithm A there exist a probability distri-

ution, D, and a learning algorithm B such that A is not better than B
w.r.t. D.

9. Consider a variant of the PAC model in which there are two example ora-
cles: one that generates positive examples and one that generates negative

examples, both according to the underlying distribution D on ¥. Formally,
given a target function f : ¥ — {0,1}, let D+ be the distribution over
X+ = {x € XV: f(x) = 1} defined by Dt (A) = D(A)/D(4*), for every
AC X&*. Similarly, D~ is the distribution over Y~ induced by D.

The definition of PAC learnability in the two-oracle model is the same as the
standard definition of PAC learnability except that here the learner has access
to mi(e, 6) iid. examples from D+ and m= (e, 6) i.i.d. examples from D~. The
learner’s goal is to output h s.t. with probability at least 1—6 (over the choice

3.5 Exercises 53

of the two training sets, and possibly over the nondeterministic decisions made
by the learning algorithm), both Lp+,,)(h) < € and L(p_,p(h) Se

1.

2.

(*) Show that if H is PAC learnable (in the standard one-oracle model),
then H is PAC learnable in the two-oracle model.

(**) Define h*+ to be the always-plus hypothesis and h~ to be the always-
minus hypothesis. Assume that h+,h~ € H. Show that if H is PAC learn-
able in the two-oracle model, then H is PAC learnable in the standard
one-oracle model.

4.1

Learning via Uniform Convergence

The first formal learning model that we have discussed was the PAC model.
In Chapter 2 we have shown that under the realizability assumption, any finite
hypothesis class is PAC learnable. In this chapter we will develop a general tool,

uniform convergence, and apply it to show that any finite class is learnable in

the agnostic PAC model with general loss functions, as long as the range loss
function is bounded.

Uniform Convergence Is Sufficient for Learnability

The idea behind the learning condition discussed in this chapter is very simple.
Recall that, given a hypothesis class, H, the ERM learning paradigm works
as follows: Upon receiving a training sample, S, the learner evaluates the risk
(or error) of each h in H on the given sample and outputs a member of H that
minimizes this empirical risk. The hope is that an h that minimizes the empirical
risk with respect to S is a risk minimizer (or has risk close to the minimum) with
respect to the true data probability distribution as well. For that, it suffices to
ensure that the empirical risks of all members of H are good approximations of
their true risk. Put another way, we need that uniformly over all hypotheses in

the hypothesis class, the empirical risk will be close to the true risk, as formalized
in the following.

DEFINITION 4.1 (e-representative sample) A training set S' is called erepresentative

(w.r.t. domain Z, hypothesis class H, loss function @, and distribution D) if
VhEH, |Ls(h) — Lo(h)| <e.

The next simple lemma states that whenever the sample is (€/2)-representative,
the ERM learning rule is guaranteed to return a good hypothesis.

LEMMA 4.2 Assume that a training set S' is $-representative (w.r.t. domain

Z, hypothesis class H, loss function ¢, and distribution D). Then, any output of
ERM y(S), namely, any hs € argmin,<7, Ls(h), satisfies

y< t
Lp(hs) < minLo(h) +e.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

4.2

4.2 Finite Classes Are Agnostic PAC Learnable 55

Proof For every h € H,
Lp(hs) < Ls(hs) + § < Ls(h) + § < Lo(h) + $+ § =Lp(h) +e,

where the first and third inequalities are due to the assumption that S' is §-

representative (Definition 4.1) and the second inequality holds since hg is an
ERM predictor.

The preceding lemma implies that to ensure that the ERM rule is an agnostic
PAC learner, it suffices to show that with probability of at least 1 — 6 over the
random choice of a training set, it will be an e-representative training set. The
uniform convergence condition formalizes this requirement.

DEFINITION 4.3 (Uniform Convergence) We say that a hypothesis class H. has
the uniform convergence property (w.r.t. a domain Z and a loss function @) if
there exists a function mf : (0,1)? + N such that for every ¢,d € (0,1) and
for every probability distribution D over Z, if S is a sample of m > mf (e, 6)
examples drawn i.i.d. according to D, then, with probability of at least 1 — 6, S
is e€-representative.

Similar to the definition of sample complexity for PAC learning, the function
m4, measures the (minimal) sample complexity of obtaining the uniform con-
vergence property, namely, how many examples we need to ensure that with
probability of at least 1 — 6 the sample would be e-representative.

The term uniform here refers to having a fixed sample size that works for all
members of H. and over all possible probability distributions over the domain.

The following corollary follows directly from Lemma 4.2 and the definition of

uniform convergence.

COROLLARY 4.4 If a class H has the uniform convergence property with a
function mip then the class is agnostically PAC learnable with the sample com-
plexity my(€,d) < mf (e/2,6). Furthermore, in that case, the ERMy, paradigm

is a successful agnostic PAC learner for H.

Finite Classes Are Agnostic PAC Learnable

In view of Corollary 4.4, the claim that every finite hypothesis class is agnostic
PAC learnable will follow once we establish that uniform convergence holds for
a finite hypothesis class.

To show that uniform convergence holds we follow a two step argument, similar
to the derivation in Chapter 2. The first step applies the union bound while the
second step employs a measure concentration inequality. We now explain these
two steps in detail.

Fix some €,5. We need to find a sample size m that guarantees that for any

D, with probability of at least 1 — 6 of the choice of S = (z1,...,2m) sampled

56

Learning via Uniform Convergence

iid. from D we have that for all h € H, |Lg(h) — Lp(h)| < €. That is,
D"({S:Vh EH, |Ls(h) — Lp(h)| < e}) > 1-4.
Equivalently, we need to show that
D™({S : dh EH, |Ls(h) — Lp(h)| > ef) <4.
Writing
{S: Sh € H,|Ls(h) — Lo(h)| > 6} = UnentS + |Es(h) — Lo(h)| > ¢},
and applying the union bound (Lemma 2.2) we obtain

D"({S: dh €H, |Lg(h) — Lp(h)| > ef) < Ss D"({S : |Lg(h) — Lp(h)| > €}).
heH
(4.1)
Our second step will be to argue that each summand of the right-hand side
of this inequality is small enough (for a sufficiently large m). That is, we will
show that for any fixed hypothesis, h, (which is chosen in advance prior to the
sampling of the training set), the gap between the true and empirical risks,
Ls(h) — Lp(h)|, is likely to be small.
Recall that Lp(h) = Ez.p[é(h, z)] and that Ls(h) = 4 i", e(h, zi). Since
each z; is sampled i.i.d. from D, the expected value of the random variable

e(h, z:) is Lp(h). By the linearity of expectation, it follows that Lp(h) is also
he expected value of Lg(h). Hence, the quantity |Lp(h)—Ls(h)| is the deviation
of the random variable Ls(h) from its expectation. We therefore need to show
hat the measure of Lg(h) is concentrated around its expected value.

A basic statistical fact, the law of large numbers, states that when m goes to
infinity, empirical averages converge to their true expectation. This is true for
Lg(h), since it is the empirical average of m i.i.d random variables. However, since

he law of large numbers is only an asymptotic result, it provides no information
about the gap between the empirically estimated error and its true value for any
given, finite, sample size.
Instead, we will use a measure concentration inequality due to Hoeffding, which

quantifies the gap between empirical averages and their expected value.

LEMMA 4.5 (Hoeffding’s Inequality) Let 01,...,0m be a sequence of i.i.d. ran-
dom variables and assume that for all i, E[0;] = 4 and Pla < 6; < b] = 1. Then,

for anye>0
m
1
Pllasea-s
i=1

The proof can be found in Appendix B.

4 < 2exp(—2me?/(b—a)).

Getting back to our problem, let 6; be the random variable ¢(h, z;). Since h

is fixed and z1,...,2m are sampled i.i.d., it follows that 01,...,0m are also iid.
L

random variables. Furthermore, Ls(h) = + 7/2, 6; and Lp(h) = p. Let us

4.2 Finite Classes Are Agnostic PAC Learnable 57

further assume that the range of ¢ is [0,1] and therefore 6; € [0,1]. We therefore
obtain that

D™({S : |Ls(h) — Lp(h)| > €}) = | ye —y 4 < 2exp(-2me’).
(4.2)
Combining this with Equation (4.1) yields
D™({S : dh EH, |Ls(h) — Lp(h)| > €}) < SY 2 exp ( —2me*)
heH

= 2|H| exp (-2me?) .

Finally, if we choose
., low(21H/8)
~ 26?
then
D"({S: dh EH, |Lg(h) — Lp(h)| > e}) < 6.

COROLLARY 4.6 Let H be a finite hypothesis class, let Z be a domain, and let
L:Hx Z — [0,1] be a loss function. Then, H enjoys the uniform convergence
property with sample complexity

. log(2/741/5)
r(e,d) < | —— |] .
mfe(e6) < [EE
Furthermore, the class is agnostically PAC learnable using the ERM algorithm
with sample complexity

maz (€,6) < mie(€/2,6) < er)

Remark 4.1 (The “Discretization Trick”) While the preceding corollary only
applies to finite hypothesis classes, there is a simple trick that allows us to get
a very good estimate of the practical sample complexity of infinite hypothesis
classes. Consider a hypothesis class that is parameterized by d parameters. For
example, let ¥ = R, Y = {+1}, and the hypothesis clas:
of the form hg(x) = sign(x — 0). That is, each hypothesis is parameterized by
one parameter, @ € R, and the hypothesis outputs 1 for all instances larger than

H, be all functions

@ and outputs —1 for instances smaller than 6. This is a hypothesis class of an
infinite size. However, if we are going to learn this hypothesis class in practice,
using a computer, we will probably maintain real numbers using floating point
representation, say, of 64 bits. It follows that in practice, our hypothesis class
is parameterized by the set of scalars that can be represented using a 64 bits
964

floating point number. There are at most such numbers; hence the actual

size of our hypothesis class is at most 2°+. More generally, if our hypothesis class

is parameterized by d numbers, in practice we learn a hypothesis class of size at
most 2°, Applying Corollary 4.6 we obtain that the sample complexity of such


58

4.3

4.4

4.5

Learning via Uniform Convergence

classes is bounded by Ansay2 Tog(2/8) | This upper bound on the sample complex-
ity has the deficiency of being dependent on the specific representation of real
numbers used by our machine. In Chapter 6 we will introduce a rigorous way
to analyze the sample complexity of infinite size hypothesis classes. Neverthe-
less, the discretization trick can be used to get a rough estimate of the sample
complexity in many practical situations.

Summary

If the uniform convergence property holds for a hypothesis class H then in most
cases the empirical risks of hypotheses in H will faithfully represent their true
risks. Uniform convergence suffices for agnostic PAC learnability using the ERM
rule. We have shown that finite hypothesis classes enjoy the uniform convergence
property and are hence agnostic PAC learnable.

Bibliographic Remarks

Classes of functions for which the uniform convergence property holds are also
called Glivenko-Cantelli classes, named after Valery Ivanovich Glivenko and
Francesco Paolo Cantelli, who proved the first uniform convergence result in
the 1930s. See (Dudley, Gine & Zinn 1991). The relation between uniform con-
vergence and learnability was thoroughly studied by Vapnik — see (Vapnik 1992,
Vapnik 1995, Vapnik 1998). In fact, as we will see later in Chapter 6, the funda-
mental theorem of learning theory states that in binary classification problems,
uniform convergence is not only a sufficient condition for learnability but is also
a necessary condition. This is not the case for more general learning problems
(see (Shalev-Shwartz, Shamir, Srebro & Sridharan 2010)).

Exercises

1. In this exercise, we show that the (€,5) requirement on the convergence of
errors in our definitions of PAC learning, is, in fact, quite close to a sim-
pler looking requirement about averages (or expectations). Prove that the
following two statements are equivalent (for any learning algorithm A, any
probability distribution D, and any loss function whose range is [0, 1]):

1. For every €,6 > 0, there exists m(e, 6) such that Vm > m(e, 6)
P [Lp(A(S)) > <6

SoD”

lim E_ [Lp(A(S))] =0

moo S~D™

4.5 Exercises 59

(where Es pm denotes the expectation over samples S' of size m).
2. Bounded loss functions: In Corollary 4.6 we assumed that the range of the
loss function is [0,1]. Prove that if the range of the loss function is [a,b] then
the sample complexity satisfies

mu(€,d) < mif (€/2,8) < ome

The Bias-Complexity Tradeoff

In Chapter 2 we saw

search space to some

us elaborate on this

h: X > Y, whose ris

°

receiving i.i.d. exam:

Is such prior know!

hypothesis class H. Such a hypothesis c
as reflecting some prior knowledge that the learner has about
hat one of the members of the class H is a low-error model
with other fruits, we may assume that some rectangle in the co
predicts (at least approximately) the papaya’s tastiness.

edge really necessary for the success 0
here exists some kind of universal learner, that is, a learner

point. A specific learning task is define
istribution D over X x Y, where the goal of the learner is

hat unless one is careful, the training data can mislead the
earner, and result in overfitting. To overcome this problem, we restricted the

ass can be viewed
the task — a belief
for the task. For

example, in our papayas taste problem, on the basis of our previous experience

lor-hardness plane

learning? Maybe
who has no prior

nowledge about a certain task and is ready to be challenged by any task? Let

d by an unknown

o find a predictor

k, Lp(h), is small enough. The question is therefore whether

The first part of this c
Lunch theorem states that no such universal

les

o have a large risk, say,
another learner that will output a hypothesis
he theorem states that no learne:
earner has tasks on whic
Therefore, when approaching a particular
istribution D, we should

ype of prior knowledge on D, whic!

> 0.3, whereas for

here exist a learning algorithm A and a training set size m, such that for every
istribution D, if A receives m i.i.d. examples from D, there is a high chance it
utputs a predictor h that has a low risk.
hapter addresses this question formally. The No-Free-
earner exists. To be more precise,
he theorem states that for binary classification prediction tasks, for every learner
here exists a distribution on which it fails. We say that the learner fails if, upon
from that distribution, its output hypothesis is likely
he same distribution, there exists
with a small risk. In other words,
r can succeed on all learnable tasks — every
h it fails while other learners succeed.

earning problem, defined by some
have some prior knowledge on D. One type of such prior
nowledge is that D comes from some specific parametric family of distributions.
We will study learning under such assumptions later on in Chapter 24. Another

h we assumed when defining the PAC learning

model, is that there exists h in some predefined hypothesis class H, such that
Lp(h) = 0. A softer type of prior knowledge on D is assuming that minnex Lp(h)

is small. In a sense, this weaker assumption on D is a prerequisite for using the

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.
Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

5.1

5.1 The No-Free-Lunch Theorem 61

agnostic PAC model, in which we require that the risk of the output hypothesis
will not be much larger than minjnex Lp(h).

In the second part of this chapter we study the benefits and pitfalls of using
a hypothesis class as a means of formalizing prior knowledge. We decompose
the error of an ERM algorithm over a class H into two components. The first
component reflects the quality of our prior knowledge, measured by the minimal
risk of a hypothesis in our hypothesis class, minnex Lp(h). This component is
also called the approximation error, or the bias of the algorithm toward choosing
a hypothesis from H. The second component is the error due to overfitting,

which depends on the size or the complexity of the class H and is called the
estimation error. These two terms imply a tradeoff between choosing a more
complex H (which can decrease the bias but increases the risk of overfitting)

or a less complex H (which might increase the bias but decreases the potential
overfitting).

The No-Free-Lunch Theorem

In this part we prove that there is no universal learner. We do this by showing
that no learner can succeed on all learning tasks, as formalized in the following
theorem:

THEOREM 5.1 (No-Free-Lunch) Let A be any learning algorithm for the task
of binary classification with respect to the 0 — 1 loss over a domain X. Let m
be any number smaller than |X|/2, representing a training set size. Then, there
exists a distribution D over X x {0,1} such that:

1. There exists a function f : X — {0,1} with Lp(f) =0.
2. With probability of at least 1/7 over the choice of S ~ D™ we have that
Lp(A(S)) > 1/8.

This theorem states that for every learner, there exists a task on which it fails,
even though that task can be successfully learned by another learner. Indeed, a
trivial successful learner in this case would be an ERM learner with the hypoth-
esis class H = {f}, or more generally, ERM with respect to any finite hypothesis
class that contains f and whose size satisfies the equation m > 8 log(7|H|/6) (see
Corollary 2.3).

Proof Let C be a subset of 4 of size 2m. The intuition of the proof is that
any learning algorithm that observes only half of the instances in C’ has no
information on what should be the labels of the rest of the instances in C.
Therefore, there exists a “reality,” that is, some target function f, that would
contradict the labels that A(S) predicts on the unobserved instances in C.
Note that there are T’ = 2?” possible functions from C to {0,1}. Denote these
functions by fi,..., fr. For each such function, let D; be a distribution over

62

The Bias-Complexity Tradeoff

C x {0,1} defined by

WIC] ify = fle)

0 otherwise.

Di({(z,y)}) = {

That is, the probability to choose a pair (x,y) is 1/|C| if the label y is indeed
the true label according to f;, and the probability is 0 if y 4 fi(x). Clearly,
Lp, (fi) = 0.

We will show that for every algorithm, A, that receives a training set of m
examples from C x {0,1} and returns a function A(S) : C — {0,1}, it holds that

max E,,[Ep,(A(S)] 21/4 (5.1)
Clearly, this means that for every algorithm, A’, that receives a training set of m
examples from ¥ x {0,1} there exist a function f : V — {0,1} and a distribution
D over X x {0,1}, such that Lp(f) = 0 and
«yal 0(A'(S))] > 1/4 (5.2)
It is easy to verify that the preceding suffices for showing that P[Lp(A’(S)) >
1/8] = 1/7, which is what we need to prove (see Exercise 1).

We now turn to proving that Equation (5.1) holds. There are k = (2m)™
possible sequences of m examples from C’. Denote these sequences by $1,..., Sx.
Also, if Sj = (x1,...,%m) we denote by Sj the sequence containing the instances
in Sj labeled by the function f;, namely, si = ((r1, fi(v1)),---,(@m, fi(@m))). If
the distribution is D; then the possible training sets A can receive are S{,..., Sj,
and all these training sets have the same probability of being sampled. Therefore,

‘
E, [Ln.(A(S))] = ¢ D> E0,(AlS})). (5.3)

SoD™

Using the facts that “maximum” is larger than “average” and that “average” is
larger than “minimum,” we have

k T k
1 , 1 1 ‘i
ax — )> _ a
max » Lp,(A(Sj)) 2 > i » Lp, (A(S}))
iwic
= 1 LY po (a1s}))
j=l i=l
iZ
> min = “)). 5.
2 min 5 3 Lp, (A(S})) (5.4)
Next, fix some j € [k]. Denote $; = (1,...,%m) and let v1,..., Up be the

examples in C' that do not appear in $;. Clearly, p > m. Therefore, for every

5.1.1

5.1 The No-Free-Lunch Theorem 63

function h : C > {0,1} and every i we have

1
Lp,(h) = 5 YS tnw@encl
xEC

3S

nw.) Afi(or)]
1

on
a

1 Pp
> De bmw Ah wo: (5.

Hence,

Lp,(A(S})) Wa(sijun)¢fi(or)]

le
Ma
IV
IR
M
Bla
Me:

La(siyonéfilvr)]

Il
Bln
iM»
S14
Ma

T
i
25° min To TasyonAfonl (5.6)

NIlR

Next, fix some r € [p]. We can partition all the functions in f1,..., fr into T/2
disjoint pairs, where for a pair (fi, fi’) we have that for every c € C, fi(c)  fir(c)
if and only if c = v,. Since for such a pair we must have si = si it follows that

Wacsiy(ve)Afe(ve)) + Tacs! oA (wn) = hs

which yields

iJ 1

F dy hatspwnr#slon) = 3

i=l

Combining this with Equation (5.6), Equation (5.4), and Equation (5.3), we

obtain that Equation (5.1) holds, which concludes our proof.

No-Free-Lunch and Prior Knowledge

How does the No-Free-Lunch result relate to the need for prior knowledge? Let us
consider an ERM predictor over the hypothesis class H of all the functions f from
X to {0,1}. This class represents lack of prior knowledge: Every possible function
from the domain to the label set is considered a good candidate. According to the
No-Free-Lunch theorem, any algorithm that chooses its output from hypotheses
in H, and in particular the ERM predictor, will fail on some learning task.
Therefore, this class is not PAC learnable, as formalized in the following corollary:

COROLLARY 5.2. Let X be an infinite domain set and let H be the set of all
functions from X to {0,1}. Then, H is not PAC learnable.

64

5.2

The Bias-Complexity Tradeoff

Proof Assume, by way of contradiction, that the class is learnable. Choose
some € < 1/8 and 6 < 1/7. By the definition of PAC learnability, there must
be some learning algorithm A and an integer m = m/(e,6), such that for any
data-generating distribution over ¥ x {0,1}, if for some function f : Y + {0,1},
Lp(f) = 0, then with probability greater than 1 — 6 when A is applied to
samples S of size m, generated i.i.d. by D, Lp(A(S)) < €. However, applying
the No-Free-Lunch theorem, since || > 2m, for every learning algorithm (and
in particular for the algorithm A), there exists a distribution D such that with
probability greater than 1/7 > 5, Lp(A(S)) > 1/8 > ¢, which leads to the
desired contradiction.

How can we prevent such failures? We can escape the hazards foreseen by the
No-Free-Lunch theorem by using our prior knowledge about a specific learning

task, to avoid the distributions that will cause us to fail when learning that task.
Such prior knowledge can be expressed by restricting our hypothesis class.

But how should we choose a good hypothesis class? On the one hand, we want:
to believe that this class includes the hypothesis that has no error at all (in the
PAC setting), or at least that the smallest error achievable by a hypothesis from
this class is indeed rather small (in the agnostic setting). On the other hand,
we have just seen that we cannot simply choose the richest class — the class of

all functions over the given domain. This tradeoff is discussed in the following
section.

Error Decomposition

To answer this question we decompose the error of an ERM predictor into two
components as follows. Let hg be an ERMy hypothesis. Then, we can write

Lp(hs) = €app téest where: €app = min Lp(h), est = Lp(hs) —€app- (5-7)

e The Approximation Error — the minimum risk achievable by a predictor
in the hypothesis class. This term measures how much risk we have because
we restrict ourselves to a specific class, namely, how much inductive bias we
have. The approximation error does not depend on the sample size and is
determined by the hypothesis class chosen. Enlarging the hypothesis class
can decrease the approximation error.

Under the realizability assumption, the approximation error is zero. In
the agnostic case, however, the approximation error can be large.!

1 Tn fact, it always includes the error of the Bayes optimal predictor (see Chapter 3), the
minimal yet inevitable error, because of the possible nondeterminism of the world in this
model. Sometimes in the literature the term approximation error refers not to
min;,cx Lp(h), but rather to the excess error over that of the Bayes optimal predictor,
namely, minne7 Lp(h) — €Bayes-

5.3

5.3 Summary 65

e The Estimation Error — the difference between the approximation error
and the error achieved by the ERM predictor. The estimation error results
because the empirical risk (ie., training error) is only an estimate of the
true risk, and so the predictor minimizing the empirical risk is only an
estimate of the predictor minimizing the true risk.

The quality of this estimation depends on the training set size and

on the size, or complexity, of the hypothesis class. As we have shown, for

a finite hypothesis class, €es_ increases (logarithmically) with |H| and de-
creases with m. We can think of the size of H as a measure of its complexity.

In future chapters we will define other complexity measures of hypothesis
classes.

Since our goal is to minimize the total risk, we face a tradeoff, called the bias-
complexity tradeoff. On one hand, choosing H to be a very rich class decreases the
approximation error but at the same time might increase the estimation error,
as a rich H might lead to overfitting. On the other hand, choosing H to be a

very small set reduces the estimation error but might increase the approximation
error or, in other words, might lead to underfitting. Of course, a great choice for
H is the class that contains only one classifier — the Bayes optimal classifier. But
the Bayes optimal classifier depends on the underlying distribution D, which we
do not know (indeed, learning would have been unnecessary had we known D).

Learning theory studies how rich we can make H while still maintaining rea-
sonable estimation error. In many cases, empirical research focuses on designing
good hypothesis classes for a certain domain. Here, “good” means classes for
which the approximation error would not be excessively high. The idea is that
although we are not experts and do not know how to construct the optimal clas-
sifier, we still have some prior knowledge of the specific problem at hand, which
enables us to design hypothesis classes for which both the approximation error

and the estimation error are not too large. Getting back to our papayas example,
we do not know how exactly the color and hardness of a papaya predict its taste,
but we do know that papaya is a fruit and on the basis of previous experience

with other fruit we conjecture that a rectangle in the color-hardness space may

be a good predictor.

Summary

The No-Free-Lunch theorem states that there is no universal learner. Every
learner has to be specified to some task, and use some prior knowledge about
that task, in order to succeed. So far we have modeled our prior knowledge by
restricting our output hypothesis to be a member of a chosen hypothesis class.

When choosing this hypothesis class, we face a tradeoff, between a larger, or

more complex, class that is more likely to have a small approximation error,
and a more restricted class that would guarantee that the estimation error will

66

5.4

5.5

The Bias-Complexi

ity Tradeoff

be small. In the next chapter we will study in more detail the behavior of the

estimation error. In
knowledge.

Chapter 7 we will discuss alternative ways to express prior

Bibliographic Remarks

(Wolpert & Macready 1997) proved several no-free-lunch theorems for optimiza-

tion, but these are rather different from the theorem we prove here. The theorem

we prove here is clo:
in the next chapter.

Exercises

sely related to lower bounds in VC theory, as we will study

1. Prove that Equation (5.2) suffices for showing that P[Lp(A(S)) > 1/8] > 1/7.
Hint: Let 6 be a random variable that receives values in [0,1] and whose

expectation satis

1/7.

fies E[6] > 1/4. Use Lemma B.1 to show that P[@ > 1/8] >

2. Assume you are asked to design a learning algorithm to predict whether pa-

tients are going

to suffer a heart attack. Relevant patient features the al-

gorithm may have access to include blood pressure (BP), body-mass index
(BMI), age (A), level of physical activity (P), and income (1).
You have to choose between two algorithms; the first picks an axis aligned

rectangle in the
and the other pi

wo dimensional space spanned by the features BP and BMI

cks an axis aligned rectangle in the five dimensional space

spanned by all the preceding features.

1. Explain the pros and cons of each choice.

2. Explain how
your choice.
3. Prove that if |v
the lower bound
Namely, let A be
m be any numbe

he number of available labeled training samples will affect

> km for a positive integer k > 2, then we can replace
of 1/4 in the No-Free-Lunch theorem with 45+ = 3 - x
a learning algorithm for the task of binary classification. Let

r smaller than ||/k, representing a training set size. Then,

there exists a dis
e There exists a

© Es.pm[Lp(A($))] = 4-4

ribution D over ¥ x {0,1} such that:
function f : ¥ > {0,1} with Lp(f) =0.

6.1

The VC-Dimension

In the previous chapter, we decomposed the error of the ERM rule into ap-
proximation error and estimation error. The approximation error depends on
the fit of our prior knowledge (as reflected by the choice of the hypothesis class
H) to the underlying unknown distribution. In contrast, the definition of PAC
learnability requires that the estimation error would be bounded uniformly over
all distributions.

Our current goal is to figure out which classes H are PAC learnable, and to
characterize exactly the sample complexity of learning a given hypothesis class.
So far we have seen that finite classes are learnable, but that the class of all
functions (over an infinite size domain) is not. What makes one class learnable

and the other unlearnable? Can infinite-size classes be learnable, and, if so, what
determines their sample complexity?

We begin the chapter by showing that infinite classes can indeed be learn-
able, and thus, finiteness of the hypothesis cle

is not a necessary condition for

learnability. We then present a remarkably crisp characterization of the family
of learnable classes in the setup of binary valued classification with the zero-one
loss. This characterization was first discovered by Vladimir Vapnik and Alexey
Chervonenkis in 1970 and relies on a combinatorial notion called the Vapnik-

Chervonenkis dimension (VC-dimension). We formally define the VC-dimension,

provide several examples, and then state the fundamental theorem of statistical
learning theory, which integrates the concepts of learnability, VC-dimension, the
ERM rule, and uniform convergence.

Infinite-Size Classes Can Be Learnable

In Chapter 4 we saw that finite classes are learnable, and in fact the sample
complexity of a hypothesis class is upper bounded by the log of its size. To show
that the size of the hypothesis class is not the right characterization of its sample

complexity, we first present a simple example of an infinite-size hypothesis class

that is learnable.

Example 6.1 Let H be the set of threshold functions over the real line, namely,
H = {ha : a € R}, where hy : R — {0,1} is a function such that ha(x) = Ie<a-
To remind the reader, Ih, <qj is 1 if 2 < a and 0 otherwise. Clearly, H is of infinite

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

68

6.2

The VC-Dimension

size. Nevertheless, the following lemma shows that H is learnable in the PAC
model using the ERM algorithm.

Lemma 6.1 Let H be the class of thresholds as defined earlier. Then, H is
PAC learnable, using the ERM rule, with sample complexity of my(e,d) <

[log(2/6)/e].

Proof Let a* be a threshold such that the hypothesis h*(x) = lhz<a+) achieves
Lp(h*) = 0. Let Dz be the marginal distribution over the domain ¥ and let
ag < a* <a, be such that

P. [x € (ao,a*)] = ody, | € (a*,a,)] =e.

awDz

€ mass € mass

ao a* ay

(If D,(—oo, a*) < € we set a9 = —oo and similarly for a1). Given a training set
S, let bop = max{zx : (x, 1) € S} and by = min{z : (#,0) € S} (if no example in S
is positive we set b) = —oo and if no example in S is negative we set bj = 00).
Let bs be a threshold corresponding to an ERM hypothesis, hs, which implies
that bs € (bo, b1). Therefore, a sufficient condition for Lp(hg) < ¢ is that both
bo > ao and b; < ay. In other words,

gcpmle(hs) >d< ge pmlbo < ao V by > ay],
and using the union bound we can bound the preceding by

< . D.
vm ED hs) >< ee ymlbo < ao] + gmt > ai] (6.1)

The event bo < ap happens if and only if all examples in S are not in the interval

(ao, a*), whose probability mass is defined to be €, namely,

Balbo < a0] = Bary) €S, @ ¢ (ag,a")] =(1=™ See.

Since we assume m > log(2/6)/e it follows that the equation is at most 6/2.
In the same way it is easy to see that Ps pm[b) > ai] < 6/2. Combining with

Equation (6.1) we conclude our proof.

The VC-Dimension

We see, therefore, that while finiteness of . is a sufficient condition for learn-
ability, it is not a necessary condition. As we will show, a property called the
VC-dimension of a hypothesis class gives the correct characterization of its learn-
ability. To motivate the definition of the VC-dimension, let us recall the No-Free-
Lunch theorem (Theorem 5.1) and its proof. There, we have shown that without

6.2 The VC-Dimension 69

restricting the hypothesis class, for any learning algorithm, an adversary can

construct a distribution for which the
while there is another learning algorit.
bution. To do so, the adversary used a
of distributions that are concentrated
derived from a “true” target function
fail, the adversary used the power of cl
all possible functions from C to {0,1}.
When considering PAC learnability

learning algorithm will perform poorly,
hm that will succeed on the same distri
finite set CC & and considered a family

T1-

on elements of C. Each distribution was
rom C’ to {0,1}. To make any algorithm
of

hoosing a target function from the se

of a hypothesis class H, the adversary

H
ed
he

is restricted to constructing distributions for which some hypothesis h €

achieves a zero risk. Since we are considering distributions that are concentra

on elements of C, we should study how H behaves on C’, which leads to
following definition.

DEFINITION 6.2 (Restriction of H to C) Let H be a class of functions from VY
to {0,1} and let C = {c1,...,¢m} C &. The restriction of H to C is the set of
functions from C to {0,1} that can be derived from H. That is,

Ho ={(h(er),-..

where we represent each function from C to {0,1} as a vector in {0, 1}!Cl.

,h(em)) +h € H},

If the restriction of H to C is the set of all functions from C to {0,
we say that H shatters the set C’. Formally:

}, then

CCX
That is,

DEFINITION 6.3 (Shat
if the restriction of H t
[Ho| = 2!C1.

A hypothesis class H shatters a finite se
of all functions from C to {0,1}.

ering)
o C is the set

Example 6.2 Let H be the class of threshold functions over R. Tal
C = {ci}. Now, if we take a = c; + 1, then we have ha(c1) = 1, and if
a = c; — 1, then we have ha(c1) = 0. Therefore, Hc is the set of all functions
from C to {0,1}, and H shatters C. Now take a set C = {c1,c2}, where
‘or the labeling (0, 1), because any threshold tha:
0 to cg as well. Therefore not all functions
hence C is not shattered by H.

e a set
we take

Cy < ce.

No h € H can account assigns
the label 0 to c; must assign the labe

from C to {0,1} are included in He;

Getting back to the construction of an adversarial distribution as in the proof
of the No-Free-Lunch theorem (Theorem 5.1), we see that whenever some set C
is shattered by H, the

a distribution over C' based on any target function from C to {0,1}, while still

adversary is not restricted by H, as they can construct

maintaining the realizability assumption. This immediately yields:

COROLLARY 6.4 Let H be a hypothesis class of functions from X to {0,1}. Let
m be a training set size. Assume that there exists a set C C &X of size 2m that is
shattered by H. Then, for any learning algorithm, A, there exist a distribution D
over X x {0,1} and a predictor h € H such that Lp(h) = 0 but with probability
of at least 1/7 over the choice of S ~D™ we have that Lp(A(S)) > 1/8.

70

6.3

6.3.1

The VC-Dimension

Corollary 6.4 tells us that if H shatters some set C' of size 2m then we cannot
learn H using m examples. Intuitively, if a set C is shattered by H, and we
receive a sample containing half the instances of C, the labels of these instances
give us no information about the labels of the rest of the instances in C — every
possible labeling of the rest of the instances can be explained by some hypothesis
in H. Philosophically,

If someone can explain every phenomenon, his explanations are worthless.

This leads us directly to the definition of the VC dimension.
DEFINITION 6.5 (VC-dimension) The VC-dimension of a hypothesis class H,
denoted VCdim(H), is the maximal size of a set C C ¥ that can be shattered
by H. If H can shatter sets of arbitrarily large size we say that H has infinite
VC-dimension.

A direct consequence of Corollary 6.4 is therefore:

THEOREM 6.6 Let H be a class of infinite VC-dimension. Then, H is not PAC
learnable.

Proof Since H has an infinite VC-dimension, for any training set size m, there

exists a shattered set of size 2m, and the claim follows by Corollary 6.4.

We shall see later in this chapter that the converse is also true: A finite VC-
dimension guarantees learnability. Hence, the VC-dimension characterizes PAC
learnability. But before delving into more theory, we first show several examples.

Examples

In this section we calculate the VC-dimension of several hypothesis classes. To
show that VCdim(H) = d we need to show that

1. There exists a set C' of size d that is shattered by H.
2. Every set C of size d+ 1 is not shattered by H.

Threshold Functions

Let H be the class of threshold functions over R. Recall Example 6.2, where
we have shown that for an arbitrary set C = {ci}, H shatters C; therefore
VCdim(H) > 1. We have also shown that for an arbitrary set C = {ci,c2} where
c1 < cz, H does not shatter C. We therefore conclude that VCdim(H) = 1.

6.3.2

6.3.3

6.3 Examples 71

Intervals

Let H be the class of intervals over R, namely, H = {ha» : a,b € R,a < Dd},
where ha, : R — {0,1} is a function such that ha»(r) = ze(a,n))- Take the set
C = {1,2}. Then, H shatters C (make sure you understand why) and therefore
VCdim(H) > 2. Now take an arbitrary set C = {c1, c2,c3} and assume without
loss of generality that cy < cg < cs. Then, the labeling (1, 0, 1) cannot be obtained
by an interval and therefore H does not shatter C’. We therefore conclude that

VCdim(#) = 2.

Axis Aligned Rectangles
Let H be the class of axis aligned rectangles, formally:

H = {hiay,a2,b1,b2) 2 4 < ag and b; < by}
where

1 ifa, <2 < ae and bj <2 <b
1221 <a 1S %2 < by (6.2)

0 otherwise

har ,a2,b1,b2) (1, ©2) = {

We shall show in the following that VCdim(H) = 4. To prove this we need
to find a set of 4 points that are shattered by H, and show that no set of 5
points can be shattered by H. Finding a set of 4 points that are shattered is
easy (see Figure 6.1). Now, consider any set CC R? of 5 points. In C, take a
leftmost point (whose first coordinate is the smallest in C), a rightmost point
(first coordinate is the largest), a lowest point (second coordinate is the smallest),
and a highest point (second coordinate is the largest). Without loss of generality,
denote C = {c1,...,¢5} and let cs; be the point that was not selected. Now,
define the labeling (1,1,1,1,0). It is impossible to obtain this labeling by an

axis aligned rectangle. Indeed, such a rectangle must contain c c4; but in

this case the rectangle contains cs as well, because its coordinates are within
the intervals defined by the selected points. So, C is not shattered by H, and
therefore VCdim(H) = 4.

C1
ca C5 C2

C3
e e

Figure 6.1 Left: 4 points that are shattered by axis aligned rectangles. Right: Any axis
aligned rectangle cannot label cs by 0 and the rest of the points by 1.

72

6.3.4

6.3.5

6.4

The VC-Dimension

Finite Classes

Let H be a finite class. Then, clearly, for any set C we have |Hc| < |H| and thus C
cannot be shattered if |H| < 2!C!. This implies that VCdim(H) < log (|H|). This
shows that the PAC learnability of finite classes follows from the more general
statement of PAC learnability of classes with finite VC-dimension, which we shall
see in the next section. Note, however, that the VC-dimension of a finite class
H can be significantly smaller than log,(|H|). For example, let ¥ = {1,...,k},
for some integer k, and consider the class of threshold functions (as defined in
Example 6.2). Then, |H| = k but VCdim(H) = 1. Since k can be arbitrarily
large, the gap between log,(|H|) and VCdim(H) can be arbitrarily large.

VC-Dimension and the Number of Parameters

In the previous examples, the VC-dimension happened to equal the number of
parameters defining the hypothesis class. While this is often the case, it is not
always true. Consider, for example, the domain V = R, and the hypothesis class
H = {ho : 0 € R} where hg : ¥ > {0,1} is defined by hg(x) = [0.5 sin(Ax)]. It
is possible to prove that VCdim(H) = oo, namely, for every d, one can find d
points that are shattered by H (see Exercise 8).

The Fundamental Theorem of PAC learning

We have already shown that a class of infinite VC-dimension is not learnable. The
converse statement is also true, leading to the fundamental theorem of statistical
learning theory:

THEOREM 6.7 (The Fundamental Theorem of Statistical Learning) Let H be a
hypothesis class of functions from a domain X to {0,1} and let the loss function
be the 0 — 1 loss. Then, the following are equivalent:

. H has the uniform convergence property.

tweoR

. Any ERM rule is a successful agnostic PAC learner for H.

we

. H is agnostic PAC learnable.

. H is PAC learnable.

. Any ERM rule is a successful PAC learner for H.
. H has a finite VC-dimension.

aan

The proof of the theorem is given in the next section.
Not only does the VC-dimension characterize PAC learnability; it even deter-
mines the sample complexity.

THEOREM 6.8 (The Fundamental Theorem of Statistical Learning — Quantita-
tive Version) Let H be a hypothesis class of functions from a domain & to {0,1}
and let the loss function be the 0 — 1 loss. Assume that VCdim(H) = d < ov.
Then, there are absolute constants C1, C2 such that:

6.5

6.5.1

6.5 Proof of Theorem 6.7 73

1. H has the uniform convergence property with sample complexity

d+ log(1/5) d+ log(1/6)
Cy —— rn

e2

< mif(e,6) < Co

2. H is agnostic PAC learnable with sample complexity

d+ log(1/6 d+ log(1/6
cee) gay(e,8) < Cy OR)
€ €
3. H is PAC learnable with sample complexity

oft Bes/?) < mu(ed) < cp Hesth/) + test/0)

The proof of this theorem is given in Chapter 28.

Remark 6.3 We stated the fundamental theorem for binary classification tasks.
A similar result holds for some other learning problems such as regression with
the absolute loss or the squared loss. However, the theorem does not hold for
all learning tasks. In particular, learnability is sometimes possible even though
the uniform convergence property does not hold (we will see an example in
Chapter 13, Exercise 2). Furthermore, in some situations, the ERM rule fails
but learnability is possible with other learning rules.

Proof of Theorem 6.7

We have already seen that 1 — 2 in Chapter 4. The implications 2 > 3 an
3 — 4 are trivial and so is 2 + 5. The implications 4 + 6 and 5 — 6 follow from
the No-Free-Lunch theorem. The difficult part is to show that 6 > 1. The proo
is based on two main claims:

e If VCdim(H) = d, then even though H might be infinite, when restricting i
to a finite set C C 4, its “effective” size, |Hc|, is only O(|C|“). That is,
the size of Hc grows polynomially rather than exponentially with |C|. This
claim is often referred to as Sauer’s lemma, but it has also been stated an
proved independently by Shelah and by Perles. The formal statement is
given in Section 6.5.1 later.

e In Section 4 we have shown that finite hypothesis classes enjoy the uniform

convergence property. In Section 6.5.2 later we generalize this result an
show that uniform convergence holds whenever the hypothesis class has a
“small effective size.” By “small effective size” we mean classes for which
|Ho| grows polynomially with |C}.

Sauer’s Lemma and the Growth Function

We defined the notion of shattering, by considering the restriction of H to a finite
set of instances. The growth function measures the maximal “effective” size of
H on a set of m examples. Formally:

74

The VC-Dimension

DEFINITION 6.9 (Growth Function) Let H be a hypothesis class. Then the
growth function of H, denoted 7 : N > N, is defined as

TyH(m) = max H.
(mm) CcXx:|Cl=m [He
In words, T77(m) is the number of different functions from a set C of size m to
{0,1} that can be obtained by restricting H to C.

Obviously, if VCdim(H) = d then for any m < d we have Ty(m) = 2. In
such cases, H induces all possible functions from C to {0,1}. The following beau-
tiful lemma, proposed independently by Sauer, Shelah, and Perles, shows that
when m becomes larger than the VC-dimension, the growth function increases
polynomially rather than exponentially with m.

LEMMA 6.10 (Sauer-Shelah-Perles) Let H. be a hypothesis class with VCdim(H) <
d<o. Then, for all m, Ty(m) < an (™). In particular, ifm > d+1 then
tu(m) < (em/d)*.

Proof of Sauer’s Lemma *
To prove the lemma it suffices to prove the following stronger claim: For any
C = {c1,...,¢m} we have

VH, |Ho| < |{B CC:H shatters B}|. (6.3)

The reason why Equation (6.3) is sufficient to prove the lemma is that if VCdim(H) <
d then no set whose size is larger than d is shattered by 1 and therefore

d
{B CC:H shatters B}| < Ss ("").
i=o \*
When m > d+ 1 the right-hand side of the preceding is at most (em/d)* (see
Lemma A.5 in Appendix A).

We are left with proving Equation (6.3) and we do it using an inductive argu-
ment. For m = 1, no matter what H is, either both sides of Equation (6.3) equal
1 or both sides equal 2 (the empty set is always considered to be shattered by
H). Assume Equation (6.3) holds for sets of size k < m and let us prove it for
sets of size m. Fix H and C = {c1,...,¢m}. Denote C’ = {c2,...,¢n} and in
addition, define the following two sets:

Yo = {(yas-+-5Ym) + (0, Y2.-.+5¥m) € He V (1, y2,---.4m) € Hc},
and

Vi = {(yo,--+5 Ym) : (0, y2,--+, Ym) € He A (1, y2,--+5 Ym) € He}.

= |Yo| + |i]. Additionally, since Yo = Hc’, using
the induction assumption (applied on H and C’) we have that

It is easy to verify that [Ho

[Yo] = |Hev| < |{B CC’: H shatters B}| = |{B CC: c, ¢ BAH shatters B}}.

6.5.2

6.5 Proof of Theorem 6.7 75

Next, define H’ C H to be
H ={heEH: dh’ €Hs.t. (L—h'(c1), h'(c2),..., 2! (Cm))
= (A(c1), h(c2),---,h(Cm)},
namely, H’ contains pairs of hypotheses that agree on C’ and differ on c;. Using
this definition, it is clear that if H’ shatters a set B C C’ then it also shatters
the set BU {c} and vice versa. Combining this with the fact that Y; = HG, and
using the inductive assumption (now applied on H’ and C’) we obtain that
Mi] =|Ho| < |{B CC’: H’ shatters B}| = |{B C C’: H’ shatters BU {c1}}|
=|{BCC:c € BAH shatters B}| < |{B CC: € BAH shatters B}|.

Overall, we have shown that
[He| = |¥o| + 1¥4|

< {BCC:c, ¢ BAH shatters B}| + |{B CC: c; € BAH shatters B}|

= |{B CC:H shatters B}|,

which concludes our proof.

Uniform Convergence for Classes of Small Effective Size

In this section we prove that if # has small effective size then it enjoys the
uniform convergence property. Formally,

THEOREM 6.11 Let H be a class and let ry be its growth function. Then, for
every D and every 6 € (0,1), with probability of at least 1 — 6 over the choice of

S~D™ we have
4+ ,/log(74(2m))
Lp(h) — Ls(h)| < ——~—-——..
[Lo(h) ~ Ls(h)| << ¥ ORT
Before proving the theorem, let us first conclude the proof of Theorem 6.7.

Proof of Theorem 6.7 It suffices to prove that if the VC-dimension is finite then
the uniform convergence property holds. We will prove that

ve 16d 16d \ , 16dlog(2e/d)
mabe) <4 es low (case) + TB

From Sauer’s lemma we have that for m > d, Ty (2m) < (2em/d)*. Combining
this with Theorem 6.11 we obtain that with probability of at least 1 — 6,

\Ls(h) — Lp(h)| < een

For simplicity assume that \/dlog(2em/d) > 4; hence,

1 /2dlog(2em/d)
|Ls(h) — Lp(h)| < 3V— om


76

The VC-Dimension

To ensure that the preceding is at most € we need that

s 2dlog(m) | 2dlog(2e/d)
m= be)? (Se?

Standard algebraic manipulations (see Lemma A.2 in Appendix A) show that a
sufficient condition for the preceding to hold is that

2d 2d \ | 4dlog(2e/d)
m2 4 Gen ls (G2) bee

Remark 6.4 The upper bound on m3? we derived in the proof Theorem 6.7

is not the tightest possible. A tighter analysis that yields the bounds given in
Theorem 6.8 can be found in Chapter 28.

Proof of Theorem 6.11 *
We will start by showing that

4+ \/log(7(2m)) .
< ——-. 6.4
< om (6.4)

Since the random variable sup, <7 |Lp(h) — Ls(h)| is nonnegative, the proof of

ism sup |Lp(h) — Ls(h)|

the theorem follows directly from the preceding using Markov’s inequality (see
Section B.1).

To bound the left-hand side of Equation (6.4) we first note that for every
h € H, we can rewrite Lp(h) = Egwpm|Lg(h)], where S” = z{,..., 2},

m is an

additional i.i.d. sample. Therefore,

oo ag en — £00] = 3. [0p Hb

A generalization of the triangle inequality yields

E_ Lg(h)— s(t)

[Lsr(h) — Ls(h)]| < .B, [Esr(h) — Es(h)|,

S'aD™

and the fact that supermum of expectation is smaller than expectation of supre-
mum yields

sup, E., |Lsi(h) - Ls(h)| <  E., sup |Ls-(h) ~ Ls(h)].

nen S'~D™ S'~D™ hen

Formally, the previous two inequalities follow from Jensen’s inequality. Combin-
ing all we obtain

s —Ls(h)|| <. E_ |s (h) — Ls
F,, [sup oh) - L(t] < , .B,,, [sup [Esr(h) - Ls]
r m
= -:E sup — U(h, 24) — &(h, 2; :
a sFpn [SUR yy led) 20)

(6.5)

The expectation on the right- han
S = 2,...,2m and S’ = 2},

ii.d., nothing will change if we replace the name o:
name of the random vector 2/. If we do it, instead

in Equation (6.5) we will have the
every o € {+1}” we have that Eq'

1
E sup —
S.S'SD™ lee

Since this holds for every o € {

he
Hence, Equation (6.5) also equals

of o uniformly at random from
E E
on S,S/SD™ | ney

and by the linearity of expectation

E E

S,S'D™ osUY

,
z,

heH ™ |e—

+1}, it also hol

1
sup —

sup —
hen ™

6.5 Proof of Theorem 6.7 77

side is over a choice of two i.i.d. samples

‘m+ Since all of these 2m vectors are chosen
the random vector z; with the
of the term (€(h, z/) — &(h, :))
) — &(h, z;)). It follows that for

uals

erm —(€(h, 2}
ation (6.5) e

m

Deailelh Zz

~ eh, |

s if we sample each component
uniform distribution over {+1}, denoted Ux.

m

SP aill(h, 24) — e(h, 2)

m
i=1

it also equals

m

Soo oi(l(h, 24) — &(h, zi)

i=1

| |

Next, fix S and S’, and let C be the instances appearing in S and S$’. Then, we
can take the supremum only over h € Hc. Therefore,

sup — Lh, 21) — L(h, %
2. {sea Dole) A |
= e 1 7 . / — .
= om max | > ai(E(h, 2) — &(h, -0| :

Fix some h € Ho and denote 6, =

ty oi(C(h, 2) — U(h, %)). Since E[6;,] = 0

and 6), is an average of independent variables, each of which takes values in

[-1, 1], we have by Hoeffding’s ine

P[l@n| > a

uality that for every p > 0,

<2 exp (-—2mp”) :

Applying the union bound over h € Ho, we obtain that for any p > 0,

P| max || >
Fea p

< 2|Ho| exp (—2m p”) .

Finally, Lemma A.4 in Appendix A tells us that the preceding implies

|

max |4;,
heHe

(Hel)
vam

}<

Combining all with the definition of 7,, we have shown that

4+ y/log(t_(2m))

78

6.6

6.7

6.8

The VC-Dimension

Summary

The fundamental theorem of learning theory characterizes PAC learnability of
classes of binary classifiers using VC-dimension. The VC-dimension of a class
is a combinatorial property that denotes the maximal sample size that can be
shattered by the class. The fundamental theorem states that a class is PAC learn-
able if and only if its VC-dimension is finite and specifies the sample complexity
required for PAC learning. The theorem also shows that if a problem is at all
learnable, then uniform convergence holds and therefore the problem is learnable
using the ERM rule.

Bibliographic remarks

The definition of VC-dimension and its relation to learnability and to uniform
convergence is due to the seminal work of Vapnik & Chervonenkis (1971). The
relation to the definition of PAC learnability is due to Blumer, Ehrenfeucht,
Haussler & Warmuth (1989).

Several generalizations of the VC-dimension have been proposed. For exam-
ple, the fat-shattering dimension characterizes learnability of some regression
problems (Kearns, Schapire & Sellie 1994, Alon, Ben-David, Cesa-Bianchi &
Haussler 1997, Bartlett, Long & Williamson 1994, Anthony & Bartlet 1999), and
the Natarajan dimension characterizes learnability of some multiclass learning
problems (Natarajan 1989). However, in general, there is no equivalence between
learnability and uniform convergence. See (Shalev-Shwartz, Shamir, Srebro &
Sridharan 2010, Daniely, Sabato, Ben-David & Shalev-Shwartz 2011).

Sauer’s lemma has been proved by Sauer in response to a problem of Erdos
(Sauer 1972). Shelah (with Perles) proved it as a useful lemma for Shelah’s theory
of stable models (Shelah 1972). Gil Kalai tells! us that at some later time, Benjy
Weiss asked Perles about such a result in the context of ergodic theory, and

Perles, who forgot that he had proved it once, proved it again. Vapnik and
Chervonenkis proved the lemma in the context of statistical learning theory.

Exercises

1. Show the following monotonicity property of VC-dimension: For every two
hypothesis classes if H’ CH then VCdim(H’) < VCdim(H).
2. Given some finite domain set, VY, and a number k < ||, figure out the VC-
dimension of each of the following classes (and prove your claims):
1. H, = {h € {0,1}* : |{x : h(x) = 1}| = k}. That is, the set of all functions
that assign the value 1 to exactly k elements of ¥.

1 http://gilkalai.wordpress .com/2008/09/28/
extremal-combinatorics-iii-some-basic-theorems

on

. VC-dimension of axis aligned rectangles in R¢: Let H

. VC-dimension of Boolean conjunctions: Let 1

6.8 Exercises 79

2. Hat—most—k = {h € {0,1}* : |{x : h(x) = 1}| < kor |{x : h(x) = 0}| < k}.

. Let X be the Boolean hypercube {0,1}". For a set I C {1,2,...,n} we define

a parity function hy as follows. On a binary vector x = (#1,2%2,...,%n) €
{0,1}",
hy(x) = (= n) mod 2.
ier

(That is, hy computes parity of bits in J.) What is the VC-dimension of the
class of all such parity functions, Hn-parity = {hr : IC {1,2,...,n}}?

. We proved Sauer’s lemma by proving that for every class H of finite VC-

dimension d, and every subset A of the domain,

d
|Ha| <|{B CA : H shatters B}| < Ss (“") .

L
i=0

Show that there are cases in which the previous two inequalities are strict
(namely, the < can be replaced by <) and cases in which they can be replaced
by equalities. Demonstrate all four combinations of = and <.

d

(oe be the class of

axis aligned rectangles in R¢. We have already seen that VCdim(H2,,) = 4.
Prove that in general, VCdim(H¢,,) = 2d.
d

fon be the class of Boolean

conjunctions over the variables 71,...,0q (d > 2). We already know that this
class is finite and thus (agnostic) PAC learnable. In this question we calculate
VCdim(H4,,,)-
1. Show that |H%,,,| < 3¢+1.
2. Conclude that VCdim(H) < dlog 3.
3. Show that H4,,, shatters the set of unit vectors {e; : i < d}.
4. (**) Show that VCdim(H4,,) < d.
Hint: Assume by contradiction that there exists a set C = {c1,...,ca+i}
that is shattered by H4,,. Let hi,...,ha41 be hypotheses in H4,, that
satisfy
. O t=j
Wiese ld +, hile) = otherwise
For each i € [d+ 1], h; (or more accurately, the conjunction that corre-
sponds to h;) contains some literal ¢; which is false on c; and true on c;
for each j 4 i. Use the Pigeonhole principle to show that there must be a
pair i<j <d+1 such that ¢; and ¢; use the same 2; and use that fact
to derive a contradiction to the requirements from the conjunctions hj, h;.
5. Consider the class H4,..,, of monotone Boolean conjunctions over {0, 1}¢.
Monotonicity here means that the conjunctions do not contain negations.

80. The VC-Dimension

7.

10.

11.

As in H4,,,, the empty conjunction is interpreted as the all-positive hy-
pothesis. We augment H%,,,,, with the all-negative hypothesis h~. Show
that VCdim(H4,.9n) = d.

We have shown that for a finite hypothesis class H, VCdim(H) < [log(|H|)].

However, this is just an upper bound. The VC-dimension of a class can be

much lower than that:

1. Find an example of a class H of functions over the real interval V = [0, 1]
such that H is infinite while VCdim(H) = 1.

2. Give an example of a finite hypothesis class H over the domain ¥ = [0, 1],

where VCdim(H) = |[logs(|H|) J.

. (*) It is often the case that the VC-dimension of a hypothesis class equals (or

can be bounded above by) the number of parameters one needs to set in order
to define each hypothesis in the class. For instance, if H is the class of axis
aligned rectangles in R¢, then VCdim(H) = 2d, which is equal to the number
of parameters used to define a rectangle in R¢. Here is an example that shows
that this is not always the case. We will see that a hypothesis class might
be very complex and even not learnable, although it has a small number of
parameters.

Consider the domain ¥ = R, and the hypothesis class
H = {x + [sin(@x)] : 0 € R}

(here, we take [—1] = 0). Prove that VCdim(H) = oo.

Hint: There is more than one way to prove the required result. One option
is by applying the following lemma: If 0.212223 ..., is the binary expansion of
x € (0,1), then for any natural number m, [sin(2™a)] = (1-2), provided
that dk >ms.t. rp = 1.

. Let H be the class of signed intervals, that is,

H = {haps :a<b,s € {-1,1}} where

_ js ifae [a,b]
hab,s(t) = { if x ¢ [a,b]

Calculate VCdim(H).
Let H be a class of functions from ¥ to {0,1}.
1. Prove that if VCdim(H) > d, for any d, then for some probability distri-
bution D over ¥ x {0,1}, for every sample size, m,
<ByalLo(A(S))] 2 min Lo(h) +
Hint: Use Exercise 3 in Chapter 5.
2. Prove that for every H that is PAC learnable, VCdim(H) < oo. (Note that
this is the implication 3 + 6 in Theorem 6.7.)
VC of union: Let Hi,...,H, be hypothesis classes over some fixed domain
set Y. Let d = max; VCdim(H;) and assume for simplicity that d > 3.


6.8 Exercises

1. Prove that
VCdim (Uj_, Hi) < 4dlog(2d) + 2log(r) .

81

Hint: Take a set of k examples and assume that they are shattered by
the union class. Therefore, the union class can produce all 2" possible
labelings on these examples. Use Sauer’s lemma to show that the union
class cannot produce more than rk@ labelings. Therefore, 2° < rk¢. Now

use Lemma, A.2.
2. (*) Prove that for r = 2 it holds that

VCdim (Hi UH2) < 2d +1.

12. Dudley classes: In this question we discuss an algebraic framework
defining concept classes over R” and show a connection between the

for

VC

dimension of such classes and their algebraic properties. Given a function

f : R" > R we define the corresponding function, POS(f) (x) = Iyp(e)s0)

. For

a class F of real valued functions we define a corresponding class of functions
POS(F) = {POS(f) : f € F}. We say that a family, F, of real valued func-
tions is linearly closed if for all f,g € F andr € R, (f + rg) € F (where
addition and scalar multiplication of functions are defined point wise, namely,
for all x € R", (f +rg)(«) = f(x) + rg(x)). Note that if a family of functions
is linearly closed then we can view it as a vector space over the reals. For a

def

function g : R” + Rand a family of functions F, let F+9 = {f+g: f € F}.
Hypothesis classes that have a representation as POS (F + g) for some vector

space of functions F and some function g are called Dudley classes.

1. Show that for every g : R" — R and every vector space of functions F as

efined earlier, VCdim(POS(F + g)) = VCdim(POS(F)).

2. (**) For every linearly closed family of real valued functions F, the VC-

F (as a vector space). Hint: Let f1,..., fa be a basis for the vector sp:

ae

hat this mapping induces a matching between functions over R" of

pot

ass:
The class HS, of halfspaces over R” (see Chapter 9).
The class HHS, of all homogeneous halfspaces over R" (see Chapter
The class Ba of all functions defined by (open) balls in R¢. Use
Dudley representation to figure out the VC-dimension of this class.

ery ene

4, Let P? denote the class of functions defined by polynomial inequali
of degree < d, namely,

imension of the corresponding class POS(F) equals the linear dimension

ACE

. Consider the mapping x +> (f1(x),..., fa(x)) (from R” to R¢). Note

he

rm POS(f) and homogeneous linear halfspaces in R¢ (the VC-dimension
the class of homogeneous linear halfspaces is analyzed in Chapter 9).

how that each of the following classes can be represented as a Dudley

he

ies

Pi= {hp : pis a polynomial of degree < din the variables x1,...,%n},

82 The VC-Dimension

where, for x = (a1..--,2n), Mp(X) = Ipcx>o} (the degree of a multi-

variable polynomial is the maximal sum of variable exponents over all

of its terms. For example, the degree of p(x) = 3a}x3 + 4a3x? is 5).

1. Use the Dudley representation to figure out the VC-dimension of the
class P? — the class of all d-degree polynomials over R.

2. Prove that the class of all polynomial classifiers over R has infinite
VC-dimension.

3. Use the Dudley representation to figure out the VC-dimension of the
class P? (as a function of d and n).

7.1

Nonuniform Learnability

The notions of PAC learnability discussed so far in the book allow the sample
sizes to depend on the accuracy and confidence parameters, but they are uniform
with respect to the labeling rule and the underlying data distribution. Conse-
quently, classes that are learnable in that respect are limited (they must have
a finite VC-dimension, as stated by Theorem 6.7). In this chapter we consider
more relaxed, weaker notions of learnability. We discuss the usefulness of such
notions and provide characterization of the concept classes that are learnable
using these definitions.

We begin this discussion by defining a notion of “nonuniform learnability” that
allows the sample size to depend on the hypothesis to which the learner is com-
pared. We then provide a characterization of nonuniform learnability and show
that nonuniform learnability is a strict relaxation of agnostic PAC learnability.

We also show that a sufficient condition for nonuniform learnability is that H is
a countable union of hypothesis classes, each of which enjoys the uniform con-
vergence property. These results will be proved in Section 7.2 by introducing a
new learning paradigm, which is called Structural Risk Minimization (SRM). In
Section 7.3 we specify the SRM paradigm for countable hypothesis classes, which
yields the Minimum Description Length (MDL) paradigm. The MDL paradigm
gives a formal justification to a philosophical principle of induction called Oc-
cam’s razor. Next, in Section 7.4 we introduce consistency as an even weaker
notion of learnability. Finally, we discuss the significance and usefulness of the
different notions of learnability.

Nonuniform Learnability

“Nonuniform learnabilit

” allows the sample size to be nonuniform with respect
to the different hypotheses with which the learner is competing. We say that a
hypothesis h is (e,5)-competitive with another hypothesis h’ if, with probability
higher than (1— 94),

Lp(h) < Lp(h’) +.

In PAC learnability, this notion of “competitiveness” is not very useful, as we

are looking for a hypothesis with an absolute low risk (in the realizable case) or

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

84

7.11

Nonuniform Learnability

with a low risk compared to the minimal risk achieved by hypotheses in our class
(in the agnostic case). Therefore, the sample size depends only on the accuracy
and confidence parameters. In nonuniform learnability, however, we allow the
sample size to be of the form m,(e, 4, ); namely, it depends also on the h with
which we are competing. Formally,

DEFINITION 7.1 A hypothesis class H is nonuniformly learnable if there exist a
learning algorithm, A, and a function m3)" : (0,1)? x H > N such that, for every
€,6 € (0,1) and for every h € H, if m > m}P"(e,6,h) then for every distribution
D, with probability of at least 1 — 6 over the choice of S ~ D™, it holds that

Lp(A(S)) < Lp(h) $e.

At this point it might be useful to recall the definition of agnostic PAC learn-
ability (Definition 3.3):
A hypothesis class H is agnostically PAC learnable if there exist a learning algo-
rithm, A, and a function my : (0,1)? +N such that, for every €,6 € (0,1) and
for every distribution D, if m > m(e,6), then with probability of at least 1 — 6
over the choice of S~D"™ it holds that

a < . y
Lp(A(S)) < pin, Lp(h') +e.
Note that this implies that for every h €H
Lp(A(S)) < Lp(h) +.

In both types of learnability, we require that the output hypothesis will be
(e,6)-competitive with every other hypothesis in the class. But the difference
between these two notions of learnability is the question of whether the sample
size m may depend on the hypothesis h to which the error of A(S') is compared.
Note that that nonuniform learnability is a relaxation of agnostic PAC learn-
ability. That is, if a class is agnostic PAC learnable then it is also nonuniformly
learnable.

Characterizing Nonuniform Learnability

Our goal now is to characterize nonuniform learnability. In the previous chapter
we have found a crisp characterization of PAC learnable classes, by showing
that a class of binary classifiers is agnostic PAC learnable if and only if its VC-
dimension is finite. In the following theorem we find a different characterization
for nonuniform learnable classes for the task of binary classification.

THEOREM 7.2 A hypothesis class H of binary classifiers is nonuniformly learn-
able if and only if it is a countable union of agnostic PAC learnable hypothesis
classes.

The proof of Theorem 7.2 relies on the following result of independent interest:

7.2

7.2 Structural Risk Minimization 85

THEOREM 7.3 Let H be a hypothesis class that can be written as a countable

union of hypothesis classes, H = Unex Hn, where each Hy enjoys the uniform

neN
convergence property. Then, H is nonuniformly learnable.

Recall that in Chapter 4 we have shown that uniform convergence is sufficient
for agnostic PAC learnability. Theorem 7.3 generalizes this result to nonuni-

form learnability. The proof of this theorem will be given in the next section by
introducing a new learning paradigm. We now turn to proving Theorem 7.2.

Proof of Theorem 7.2 First assume that H = U,,cy
nostic PAC learnable. Using the fundamental theorem of statistical learning, it

H,, where each H,, is ag-

follows that each H,, has the uniform convergence property. Therefore, using
Theorem 7.3 we obtain that H is nonuniform learnable.

For the other direction, assume that H is nonuniform learnable using some
algorithm A. For every n € N, let Hn = {h € H : m3P"(1/8,1/7,h) < n}.

NUL

Clearly, H = UnenHn. In addition, using the definition of m3" we know that
for any distribution D that satisfies the realizability assumption with respect to
Hy, with probability of at least 6/7 over S ~ D” we have that Lp(A(S)) < 1/8.

Using the fundamental theorem of statistical learning, this implies that the VC-

dimension of H,, must be finite, and therefore H,, is agnostic PAC learnable.

The following example shows that nonuniform learnability is a strict relax-

ation of agnostic PAC learnability; namely, there are hypothesis classes that are
nonuniform learnable but are not agnostic PAC learnable.

Example 7.1 Consider a binary classification problem with the instance domain

being ¥ = R. For every n € N let H, be the class of polynomial classifiers of
degree n; namely, Hy, is the set of all classifiers of the form h(a) = sign(p(z))
where p: R > R is a polynomial of degree n. Let H = Unen H,,. Therefore, 1 is
the class of all polynomial classifiers over R. It is easy to verify that VCdim(H) =
oo while VCdim(H,,) = n + 1 (see Exercise 12). Hence, H is not PAC learnable,
while on the basis of Theorem 7.3, H is nonuniformly learnable.

Structural Risk Minimization

So far, we have encoded our prior knowledge by specifying a hypothesis class
H, which we believe includes a good predictor for the learning task at hand.
Yet another way to express our prior knowledge is by specifying preferences over
hypotheses within H. In the Structural Risk Minimization (SRM) paradigm,
we do so by first assuming that H can be written as H = Ucn Hn and then
specifying a weight function, w : N — [0,1], which assigns a weight to each
hypothesis class, Hn, such that a higher weight reflects a stronger preference
for the hypothesis class. In this section we discuss how to learn with such prior
knowledge. In the next section we describe a couple of important weighting
schemes, including Minimum Description Length.

86

Nonuniform Learnability

Concretely, let H be a hypothesis class that can be written as H = Uncen Hn-
For example, H may be the class of all polynomial classifiers where each H,, is
the class of polynomial classifiers of degree n (see Example 7.1). Assume that for
each n, the class H.,, enjoys the uniform convergence property (see Definition 4.3
in Chapter 4) with a sample complexity function my (€, 6). Let us also define
the function e,, : N x (0,1) + (0,1) by

€n(m, 6) = min{e € (0,1) : m¥P (€,5) < m}. (7.1)

In words, we have a fixed sample size m, and we are interested in the lowest
possible upper bound on the gap between empirical and true risks achievable by
using a sample of m examples.

From the definitions of uniform convergence and €,,, it follows that for every
m and 6, with probability of at least 1 — 6 over the choice of S ~ D™ we have
that

VhE Hn, |Lp(h) — Lg(h)| < €n(m,6). (7.2)

Let w: N > [0,1] be a function such that [°° w(n) < 1. We refer to w as
a weight function over the hypothesis classes H;,H2,.... Such a weight function
can reflect the importance that the learner attributes to each hypothesis class,
or some measure of the complexity of different hypothesis classes. If H is a finite
union of N hypothesis classes, one can simply assign the same weight of 1/N to
all hypothesis classes. This equal weighting corresponds to no a priori preference
to any hypothesis class. Of course, if one believes (as prior knowledge) that a
certain hypothesis class is more likely to contain the correct target function,
then it should be assigned a larger weight, reflecting this prior knowledge. When
H. is a (countable) infinite union of hypothesis classes, a uniform weighting is
not possible but many other weighting schemes may work. For example, one can

choose w(n) = ato or w(n) = 2~”. Later in this chapter we will provide another

convenient way to define weighting functions using description languages.

The SRM rule follows a “bound minimization” approach. This means that

the goal of the paradigm is to find a hypothesis that minimizes a certain upper
bound on the true risk. The bound that the SRM rule wishes to minimize is
given in the following theorem.

THEOREM 7.4 Let w:N — [0,1] be a function such that 0°, w(n) < 1. Let
H. be a hypothesis class that can be written as H = Unen H,,, where for each n,
H,, satisfies the uniform convergence property with a sample complexity function
my. Let €, be as defined in Equation (7.1). Then, for every 6 € (0,1) and
distribution D, with probability of at least 1— 6 over the choice of S~D"™, the

following bound holds (simultaneously) for everyn € N and h € Hy.
|Lp(h) — Lg(h)| < €n(m, w(n) - 4).

Therefore, for every 6 € (0,1) and distribution D, with probability of at least

7.2 Structural Risk Minimization 87

1—6 it holds that

VREH, Lp(h) <Ls(h)+ min e,(m,w(n)- 6d). (7.3)

n:hEHn
Proof For each n define 6, = w(n)d. Applying the assumption that uniform
convergence holds for all n with the rate given in Equation (7.2), we obtain that
if we fix nm in advance, then with probability of at least 1 — 6, over the choice o:

S ~ Dp”,
VhE€ Hn, |Lo(h) — Ls(h)| < €n(m, bn).
Applying the union bound over n = 1,2,..., we obtain that with probability o:

at least 1-9, bn =1—0 55, w(n) > 1-6, the preceding holds for all n, which
concludes our proof.

Denote
n(h) = min{n:h € Hy}, (7.4)
and then Equation (7.3) implies that
Lp(h) < Lg(h) + En(ny(m, w(n(h)) - 6).

The SRM paradigm searches for h that minimizes this bound, as formalized
in the following pseudocode:

Structural Risk Minimization (SRM)

prior knowledge:
H =U, Hn where H, has uniform convergence with map
w:N-— [0,1] where 55, w(n) <1
define: ¢, as in Equation (7.1) ; n(h) as in Equation (7.4)
input: training set S ~ D™, confidence 6
output: h € argminycy [Ls(h) + €niny)(m, w(n(h)) - 6)]

Unlike the ERM paradigm discussed in previous chapters, we no longer just care
about the empirical risk, Lg(h), but we are willing to trade some of our bias

toward low empirical risk with a bias toward classes for which €,,(,)(m, w(n(h))-6)

is smaller, for the sake of a smaller estimation error.

Next we show that the SRM paradigm can be used for nonuniform learning
of every class, which is a countable union of uniformly converging hypothesis
classes.

THEOREM 7.5 Let H be a hypothesis class such that H = Unen
each Hy, has the uniform convergence property with sample complexity may. Let
w:N - [0,1] be such that w(n) = sez. Then, H is nonuniformly learnable
using the SRM rule with rate

my (€,0,h) < me, (</2. atte)

Hn, where

88

Nonuniform Learnability

Proof Let A be the SRM algorithm with respect to the weighting function w.
For every h € H, €, and 4, let m > mf, (€,w(n(h))6). Using the fact that
x, w(n) = 1, we can apply Theorem 7.4 to get that, with probability of at least
1 —6 over the choice of S ~ D™, we have that for every h’ € H,

Lo(h’) < Ls(h’) + enany(m, w(n(h’))6).

The preceding holds in particular for the hypothesis A(S) returned by the SRM
rule. By the definition of SRM we obtain that

Lp(A(S)) < min [Ls(h’) + envy (m, w(n(h'))5)] < Lg(h) + €ncny(m, w(n(h))6).

Finally, if m > m3f, ,, (€/2, w(n(h))6) then clearly €,(n)(m, w(n(h))5) < €/2. In
addition, from the uniform convergence property of each H,, we have that with
probability of more than 1 — 6,

Lg(h) < Lp(h) + €/2.

Combining all the preceding we obtain that Lp(A(S)) < Lp(h) + €, which con-
cludes our proof.

Note that the previous theorem also proves Theorem 7.3.

Remark 7.2 (No-Free-Lunch for Nonuniform Learnability) We have shown that
any countable union of classes of finite VC-dimension is nonuniformly learnable.

It turns out that, for any infinite domain set, ¥, the class of all binary valued
functions over ¥ is not a countable union of classes of finite VC-dimension. We
leave the proof of this claim as a (nontrivial) exercise (see Exercise 5). It follows
that, in some sense, the no free lunch theorem holds for nonuniform learning
as well: namely, whenever the domain is not finite, there exists no nonuniform
learner with respect to the class of all deterministic binary classifiers (although
for each such classifier there exists a trivial algorithm that learns it - ERM with
respect to the hypothesis class that contains only this classifier).

It is interesting to compare the nonuniform learnability result given in The-
orem 7.5 to the task of agnostic PAC learning any specific H, separately. The
prior knowledge, or bias, of a nonuniform learner for 1 is weaker — it is searching
‘or a model throughout the entire class H, rather than being focused on one spe-
cific H,. The cost of this weakening of prior knowledge is the increase in sample
complexity needed to compete with any specific h € H,. For a concrete evalua-
ion of this gap, consider the task of binary classification with the zero-one loss.
Assume that for all n, VCdim(H,,) = n. Since m¥P (€,6) = C nrtlog(t/s) (where
C is the contant appearing in Theorem 6.8), a straightforward calculation shows
hat
2log(2n)

>

m3," (€,6,h) — myP (€/2,6) < 4C

€

That is, the cost of relaxing the learner’s prior knowledge from a specific Hy,

hat contains the target h to a countable union of classes depends on the log of

7.3

7.3, Minimum Description Length and Occam’s Razor 89

the index of the first class in which h resides. That cost increases with the index
of the class, which can be interpreted as reflecting the value of knowing a good
priority order on the hypotheses in H.

Minimum Description Length and Occam’s Razor

Let H be a countable hypothesis class. Then, we can write H as a countable
union of singleton classes, namely, H = U,en{hn}- By Hoeffding’s inequality
(Lemma 4.5), each singleton class has the uniform convergence property with
rate m°°(e,d) = og(2/9) Therefore, the function €, given in Equation (7.1)

becomes €,,(m, 6) = 4/ Jes(2/4) and the SRM rule becomes

—log(w(n)) + Tog(2/8) |

2m

argmin
NnEH

Lg(h) t

Equivalently, we can think of w as a function from H to [0, 1], and then the SRM
rule becomes

argmin
hEeH

Ls(h) 4 [eee ee)

2m

It follows that in this case, the prior knowledge is solely determined by the weight

we assign to each hypothesis. We assign higher weights to hypotheses that we
believe are more likely to be the correct one, and in the learning algorithm we
prefer hypotheses that have higher weights.

In this section we discuss a particular convenient way to define a weight func-
tion over H,, which is derived from the length of descriptions given to hypotheses.
Having a hypothesis class, one can wonder about how we describe, or represent,
each hypothesis in the class. We naturally fix some description language. This
can be English, or a programming language, or some set of mathematical formu-
las. In any of these languages, a description consists of finite strings of symbols
(or characters) drawn from some fixed alphabet. We shall now formalize these
notions.

Let H be the hypothesis class we wish to describe. Fix some finite set ¥

of symbols (or “characters”), which we call the alphabet. For concreteness, we
let © = {0,1}. A string is a finite sequence of symbols from ©; for example,
o = (0,1,1,1,0) is a string of length 5. We denote by |o| the length of a string.
The set of all finite length strings is denoted &*. A description language for H.
is a function d: H + X*, mapping each member h of H to a string d(h). d(h) is
called “the description of h,” and its length is denoted by |h|.

We shall require that description languages be prefix-free; namely, for every
distinct h,h’, d(h) is not a prefix of d(h’). That is, we do not allow that any
string d(h) is exactly the first |h| symbols of any longer string d(h’). Prefix-free

collections of strings enjoy the following combinatorial property:

90

Nonuniform Learnability

LEMMA 7.6 (Kraft Inequality) IfS C {0,1}* is a prefiz-free set of strings, then
1
Do gai <1
acs 2

Proof Define a probability distribution over the members of S as follows: Re-
peatedly toss an unbiased coin, with faces labeled 0 and 1, until the sequence

of outcomes is a member of S; at that point, stop. For each o € S, let P(o)
be the probability that this process generates the string o. Note that since S is
prefix-free, for every o € S, if the coin toss outcomes follow the bits of o then
we will stop only once the sequence of outcomes equals a. We therefore get that,

for every 9 € S, P(o) = sur Since probabilities add up to at most 1, our proof

is concluded.

In light of Kraft’s inequality, any prefix-free description language of a hypoth-

esis class, 1, gives rise to a weighting function w over that hypothesis class — we
will simply set w(h) = aH This observation immediately yields the following:

THEOREM 7.7 Let H be a hypothesis class and let d: H — {0,1}* be a prefiz-
free description language for H. Then, for every sample size, m, every confidence
parameter, 6 > 0, and every probability distribution, D, with probability greater
than 1—6 over the choice of S~D™ we have that,

h| + In(2/6)

2m

VhEH, Lp(h) <Ls(h) +

where |h| is the length of d(h).

Proof Choose w(h) = 1/2!"!, apply Theorem 7.4 with €,(m, 6) = 4/ nis) | and
note that In(2!"!) = |A|In(2) < AJ.

As was the case with Theorem 7.4, this result suggests a learning paradigm
for H — given a training set, S, search for a hypothesis h € H that minimizes

the bound, Ls(h) + 4/ (altin(@2/9) | In particular, it suggests trading off empirica

risk for saving description length. This yields the Minimum Description Length
learning paradigm.

Minimum Description Length (MDL)

prior knowledge:

H is a countable hypothesis class

H. is described by a prefix-free language over {0, 1}

For every h € H, |h| is the length of the representation of h
input: A training set S ~ D™, confidence 6

output: h € argmin, [est + (Sea)

2m

Example 7.3 Let H be the cl
some programming language, s

s of all predictors that can be implemented using

y, C++. Let us represent each program using the

7.3.1

7.3, Minimum Description Length and Occam’s Razor 91

binary string obtained by running the gzip command on the program (this yields
a prefix-free description language over the alphabet {0,1}). Then, |h| is simply
the length (in bits) of the output of gzip when running on the C++ program
corresponding to h.

Occam's Razor

Theorem 7.7 suggests that, having two hypotheses sharing the same empirical
tisk, the true risk of the one that has shorter description can be bounded by a
lower value. Thus, this result can be viewed as conveying a philosophical message:

A short explanation (that is, a hypothesis that has a short length) tends to be more valid
than a long explanation.

This is a well known principle, called Occam’s razor, after William of Ockham,
a 14th-century English logician, who is believed to have been the first to phrase
it explicitly. Here, we provide one possible justification to this principle. The
inequality of Theorem 7.7 shows that the more complex a hypothesis h is (in the
sense of having a longer description), the larger the sample size it has to fit to
guarantee that it has a small true risk, Lp(h).

At asecond glance, our Occam razor claim might seem somewhat problematic.
In the context in which the Occam razor principle is usually invoked in science,
he language according to which complexity is measured is a natural language,
whereas here we may consider any arbitrary abstract description language. As-

sume that we have two hypotheses such that |h’| is much smaller than |h|. By
he preceding result, if both have the same error on a given training set, S, then
he true error of h may be much higher than the true error of h’, so one should
prefer h’ over h. However, we could have chosen a different description language,
say, one that assigns a string of length 3 to h and a string of length 100000 to h’.
Suddenly it looks as if one should prefer h over h’. But these are the same h and
h’ for which we argued two sentences ago that h’ should be preferable. Where is
he catch here?

Indeed, there is no inherent generalizability difference between hypotheses.

The crucial aspect here is the dependency order between the initial choice of
anguage (or, preference over hypotheses) and the training set. As we know from

he basic Hoeffding’s bound (Equation (4.2)), if we commit to any hypothesis be-
fore seeing the data, then we are guaranteed a rather small estimation error term
Lp(h) < Ls(h) + \/ C/o) Choosing a description language (or, equivalently,
some weighting of hypotheses) is a weak form of committing to a hypothesis.
Rather than committing to a single hypothesis, we spread out our commitment
among many. As long as it is done independently of the training sample, our gen-

eralization bound holds. Just as the choice of a single hypothesis to be evaluated
by a sample can be arbitrary, so is the choice of description language.

92

7.4

Nonuniform Learnability

Other Notions of Learnability — Consistency

The notion of learnability can be further relaxed by allowing the needed sample
sizes to depend not only on e, 6, and h but also on the underlying data-generating
probability distribution D (that is used to generate the training sample and to
determine the risk). This type of performance guarantee is captured by the notion
of consistency! of a learning rule.

DEFINITION 7.8 (Consistency) Let Z be a domain set, let P be a set of
probability distributions over Z, and let H be a hypothesis class. A learn-
ing rule A is consistent with respect to H and P if there exists a function
me : (0,1)? x H x P +N such that, for every €,6 € (0,1), every h € H, and
every D € P, ifm > m3/P"(€,6,h,D) then with probability of at least 1 — 6 over
the choice of S ~ D™ it holds that

Lp(A(S)) < Lp(h) $e.

If P is the set of all distributions,” we say that A is universally consistent with
respect to H.

The notion of consistency is, of course, a relaxation of our previous notion
of nonuniform learnability. Clearly if an algorithm nonuniformly learns a class
H it is also universally consistent for that class. The relaxation is strict in the
sense that there are consistent learning rules that are not successful nonuniform
learners. For example, the algorithm Memorize defined in Example 7.4 later is
universally consistent for the class of all binary classifiers over N. However, as
we have argued before, this class is not nonuniformly learnable.

Example 7.4 Consider the classification prediction algorithm Memorize defined
as follows. The algorithm memorizes the training examples, and, given a test
point x, it predicts the majority label among all labeled instances of x that exist

in the training sample (and some fixed default label if no instance of x appears

in the training set). It is possible to show (see Exercise 6) that the Memorize
algorithm is universally consistent for every countable domain ¥ and a finite
label set Y (w.r.t. the zero-one loss).

Intuitively, it is not obvious that the Memorize algorithm should be viewed as a
learner, since it lacks the aspect of generalization, namely, of using observed data

to predict the labels of unseen examples. The fact that Memorize is a consistent
algorithm for the class of all functions over any countable domain set therefore

raises doubt about the usefulness of consistency guarantees. Furthermore, the

sharp-eyed reader may notice that the “bad learner” we introduced in Chapter 2,

1 In the literature, consistency is often defined using the notion of either convergence in
probability (corresponding to weak consistency) or almost sure convergence (corresponding
to strong consistency).

? Formally, we assume that Z is endowed with some sigma algebra of subsets Q, and by “all
distributions” we mean all probability distributions that have Q contained in their
associated family of measurable subsets.

7.5

7.5 Discussing the Different Notions of Learnability 93

which led to overfitting, is in fact the Memorize algorithm. In the next section
we discuss the significance of the different notions of learnability and revisit the
No-Free-Lunch theorem in light of the different definitions of learnability.

Discussing the Different Notions of Learnability

We have given three definitions of learnability and we now discuss their useful-
ness. As is usually the case, the usefulness of a mathematical definition depends
on what we need it for. We therefore list several possible goals that we aim to
achieve by defining learnability and discuss the usefulness of the different defini-
tions in light of these goals.

What Is the Risk of the Learned Hypothesis?
The first possible goal of deriving performance guarantees on a learning algo-
rithm is bounding the risk of the output predictor. Here, both PAC learning
and nonuniform learning give us an upper bound on the true risk of the learned
hypothesis based on its empirical risk. Consistency guarantees do not provide

such a bound. However, it is always possible to estimate the risk of the output
predictor using a validation set (as will be described in Chapter 11).

How Many Examples Are Required to Be as Good as the Best Hypothesis
in H?
When approaching a learning problem, a natural question is how many exam-
ples we need to collect in order to learn it. Here, PAC learning gives a crisp
answer. However, for both nonuniform learning and consistency, we do not know
in advance how many examples are required to learn . In nonuniform learning
this number depends on the best hypothesis in H, and in consistency it also
depends on the underlying distribution. In this sense, PAC learning is the only
useful definition of learnability. On the flip side, one should keep in mind that
even if the estimation error of the predictor we learn is small, its risk may still
be large if H has a large approximation error. So, for the question “How many
examples are required to be as good as the Bayes optimal predictor?” even PAC
guarantees do not provide us with a crisp answer. This reflects the fact that the
usefulness of PAC learning relies on the quality of our prior knowledge.

PAC guarantees also help us to understand what we should do next if our
learning algorithm returns a hypothesis with a large risk, since we can bound
the part of the error that stems from estimation error and therefore know how

much of the error is attributed to approximation error. If the approximation error

is large, we know that we should use a different hypothesis class. Similarly, if a
nonuniform algorithm fails, we can consider a different weighting function over

(subsets of) hypotheses. However, when a consistent algorithm fails, we have

no idea whether this is because of the estimation error or the approximation

error. Furthermore, even if we are sure we have a problem with the estimation

94

Nonuniform Learnability

error term, we do not know how many more examples are needed to make the
estimation error small.

How to Learn? How to Express Prior Knowledge?
Maybe the most useful aspect of the theory of learning is in providing an answer
to the question of “how to learn.” The definition of PAC learning yields the
limitation of learning (via the No-Free-Lunch theorem) and the necessity of prior
knowledge. It gives us a crisp way to encode prior knowledge by choosing a
hypothesis class, and once this choice is made, we have a generic learning rule —
ERM. The definition of nonuniform learnability also yields a crisp way to encode
prior knowledge by specifying weights over (subsets of) hypotheses of H. Once
this choice is made, we again have a generic learning rule~ SRM. The SRM rule
is also advantageous in model selection tasks, where prior knowledge is partial.
We elaborate on model selection in Chapter 11 and here we give a brief example.
Consider the problem of fitting a one dimensional polynomial to data; namely,
our goal is to learn a function, h : R > R, and as prior knowledge we consider
the hypothesis class of polynomials. However, we might be uncertain regarding
which degree d would give the best results for our data set: A small degree might
not fit the data well (i-e., it will have a large approximation error), whereas a
high degree might lead to overfitting (i-e., it will have a large estimation error).

In the following we depict the result of fitting a polynomial of degrees 2, 3, and
10 to the same training set.

fal

egree 2 legree 3 egree 10

, Vo H

cy a aa ¥ SS + PAS oe

It is easy to see that the empirical risk decreases as we enlarge the degree.

Therefore, if we choose H to be the class of all polynomials up to degree 10 then

the ERM rule with respect to this class would output a 10 degree polynomia
and would overfit. On the other hand, if we choose too small a hypothesis class,

say, polynomials up to degree 2, then the ERM would suffer from underfitting

(i.e., a large approximation error). In contrast, we can use the SRM rule on the
set of all polynomials, while ordering subsets of H according to their degree, and
this will yield a 3rd degree polynomial since the combination of its empirical

risk and the bound on its estimation error is the smallest. In other words, the
SRM rule enables us to select the right model on the basis of the data itself. The
price we pay for this flexibility (besides a slight increase of the estimation error
relative to PAC learning w.r.t. the optimal degree) is that we do not know in


7.5.1

7.5 Discussing the Different Notions of Learnability 95

advance how many examples are needed to compete with the best hypothesis in
H.

Unlike the notions of PAC learnability and nonuniform learnability, the defini-
tion of consistency does not yield a natural learning paradigm or a way to encode
prior knowledge. In fact, in many cases there is no need for prior knowledge at
all. For example, we saw that even the Memorize algorithm, which intuitively
should not be called a learning algorithm, is a consistent algorithm for any class
defined over a countable domain and a finite label set. This hints that consistency
is a very weak requirement.

Which Learning Algorithm Should We Prefer?

One may argue that even though consistency is a weak requirement, it is desirable
that a learning algorithm will be consistent with respect to the set of all functions
from 4 to Y, which gives us a guarantee that for enough training examples, we
will always be as good as the Bayes optimal predictor. Therefore, if we have
two algorithms, where one is consistent and the other one is not consistent, we
should prefer the consistent algorithm. However, this argument is problematic for
two reasons. First, maybe it is the case that for most “natural” distributions we
will observe in practice that the sample complexity of the consistent algorithm
will be so large so that in every practical situation we will not obtain enough
examples to enjoy this guarantee. Second, it is not very hard to make any PAC

or nonuniform learner consistent with respect to the class of all functions from
X to Y. Concretely, consider a countable domain, 7%, a finite label set Y, and

a hypothesis class, H, of functions from 4 to Y. We can make any nonuniform

learner for H. be consistent with respect to the class of all classifiers from Y to Y
using the following simple trick: Upon receiving a training set, we will first run
the nonuniform learner over the training set, and then we will obtain a bound
on the true risk of the learned predictor. If this bound is small enough we are

done. Otherwise, we revert to the Memorize algorithm. This simple modification

makes the algorithm consistent with respect to all functions from ¥ to Y. Since
it is easy to make any algorithm consistent, it may not be wise to prefer one

algorithm over the other just because of consistency considerations.

The No-Free-Lunch Theorem Revisited

Recall that the No-Free-Lunch theorem (Theorem 5.1 from Chapter 5) implies
that no algorithm can learn the class of all classifiers over an infinite domain.
In contrast, in this chapter we saw that the Memorize algorithm is consistent
with respect to the class of all classifiers over a countable infinite domain. To
understand why these two statements do not contradict each other, let us first
recall the formal statement of the No-Free-Lunch theorem.

Let ¥ be a countable infinite domain and let = {+1}. The No-Free-Lunch
theorem implies the following: For any algorithm, A, and a training set size, m,
there exist a distribution over ¥ and a function h* : & > Y, such that if A


96

7.6

Nonuniform Learnability

will get a sample of m i.i.d. training examples, labeled by h*, then A is likely to
return a classifier with a larger error.

The consistency of Memorize implies the following: For every distribution over
& and a labeling function h* : X — J, there exists a training set size m (that
depends on the distribution and on h*) such that if Memorize receives at least
m examples it is likely to return a classifier with a small error.

We see that in the No-Free-Lunch theorem, we first fix the training set size,
and then find a distribution and a labeling function that are bad for this training
set size. In contrast, in consistency guarantees, we first fix the distribution and
the labeling function, and only then do we find a training set size that suffices
for learning this particular distribution and labeling function.

Summary

We introduced nonuniform learnability as a relaxation of PAC learnability and
consistency as a relaxation of nonuniform learnability. This means that even
classes of infinite VC-dimension can be learnable, in some weaker sense of learn-
ability. We discussed the usefulness of the different definitions of learnability.
For hypothesis classes that are countable, we can apply the Minimum Descrip-
ion Length scheme, where hypotheses with shorter descriptions are preferred,
‘ollowing the principle of Occam’s razor. An interesting example is the hypothe-
sis class of all predictors we can implement in C++ (or any other programming
anguage), which we can learn (nonuniformly) using the MDL scheme.

Arguably, the class of all predictors we can implement in C++ is a powerful

ass of functions and probably contains all that we can hope to learn in prac-

ice. The ability to learn this class is impressive, and, seemingly, this chapter

nD

hould have been the last chapter of this book. This is not the case, because of
he computational aspect of learning: that is, the runtime needed to apply the

earning rule. For example, to implement the MDL paradigm with respect to
all C++ programs, we need to perform an exhaustive search over all C++ pro-
grams, which will take forever. Even the implementation of the ERM paradigm

with respect to all C++ programs of description length at most 1000 bits re-

quires an exhaustive search over 2! hypotheses. While the sample complexity
0 1000+log(2/5)
a

learning this class is just , the runtime is > 210°, This is a huge

number — much larger than the number of atoms in the visible universe. In the

next chapter we formally define the computational complexity of learning. In the
second part of this book we will study hypothesis classes for which the ERM or
SRM schemes can be implemented efficiently.

7.7

7.8

7.7 Bibliographic Remarks 97

Bibliographic Remarks

Our definition of nonuniform learnability is related to the definition of an Occam-
algorithm in Blumer, Ehrenfeucht, Haussler & Warmuth (1987). The concept of
SRM is due to (Vapnik & Chervonenkis 1974, Vapnik 1995). The concept of MDL
is due to (Rissanen 1978, Rissanen 1983). The relation between SRM and MDL
is discussed in Vapnik (1995). These notions are also closely related to the notion
of regularization (e.g. Tikhonov (1943)). We will elaborate on regularization in
the second part of this book.

The notion of consistency of estimators dates back to Fisher (1922). Our pre-
sentation of consistency follows Steinwart & Christmann (2008), who also derived
several no-free-lunch theorems.

Exercises

1. Prove that for any finite class H, and any description language d : H —>
{0,1}*, the VC-dimension of H is at most 2sup{|d(h)| : h € H} — the maxi-
mum description length of a predictor in H. Furthermore, if d is a prefix-free
description then VCdim(H) < sup{|d(h)| : h © H}.

2. Let H = {hy : n € N} be an infinite countable hypothesis class for binary
classification. Show that it is impossible to assign weights to the hypotheses
in H such that.

e H could be learnt nonuniformly using these weights. That is, the weighting
function w : H — [0,1] should satisfy the condition }7),-4,w(h) < 1.

e The weights would be monotonically nondecreasing. That is, if i < j, then
w(hi) < w(hy).

3. e Consider a hypothesis class H = U?-, Hn, where for every n € N, Hy is

finite. Find a weighting function w : H — [0,1] such that }7),¢4, w(h) <
1 and so that for all h € H, w(h) is determined by n(h) = min{n: h €
Hn} and by |Hnny|-

e (*) Define such a function w when for all n H,, is countable (possibly
infinite).

4. Let H be some hypothesis class. For any h € H, let |h| denote the description
length of h, according to some fixed description language. Consider the MDL
learning paradigm in which the algorithm returns:

lhl + men

hs € arg min [ese + un

where S$ is a sample of size m. For any B > 0, let Hg = {h € H: |h| < B},
and define

hp = arg min Lp(h).

98

Nonuniform_Learnability

Prove a bound on Lp(hs)—Lp(hjz) in terms of B, the confidence parameter

6, and the size of the training set m.

e Note: Such bounds are known as oracle inequalities in the literature: We

wish to estimate how good we are compared to a reference classifier (or
“oracle”) hi,.

. In this question we wish to show a No-Free-Lunch result for nonuniform learn-

ability: namely, that, over any infinite domain, the class of all functions is not

on

learnable even under the relaxed nonuniform variation of learning.

Recall that an algorithm, A, nonuniformly learns a hypothesis class H if

here exists a function m3?" : (0,1)? x H — N such that, for every ¢,6 € (0,1)
and for every h € H, if m > m3P"(e,6,h) then for every distribution D, with
probability of at least 1 — 6 over the choice of S ~ D™, it holds that

Lp(A(S)) < Lo(h) +6

If such an algorithm exists then we say that H is nonuniformly learnable.

. Let A be a nonuniform learner for a class H. For each n € N define H4 =

{h © H: mX""(0.1,0.1,h) < n}. Prove that each such class H,, has a finite
VC-dimension.

Prove that if a class H is nonuniformly learnable then there are classes H.»,
so that H = Ucn Hn and, for every n € N, VCdim(H,,) is finite.

Let H be a class that shatters an infinite set. Then, for every sequence
of classes (H, : n € N) such that H = U
which VCdim(H,,) = co.

Hint: Given a class H that shatters some infinite set K, and a sequence of
classes (H,:n € N), each having a finite VC-dimension, start by defining
subsets K, C K such that, for all n, |K,| > VCdim(H,,) and for any
n#ém, K,A Km =. Now, pick for each such K,, a function fy: Ky >
{0,1} so that no h € H, agrees with f, on the domain K,,. Finally, define
f :X — {0,1} by combining these f,,’s and prove that f € (H \Unen Hn).
Construct a class H, of functions from the unit interval (0, 1] to {0,1} that

neN Hn, there exists some n for

is nonuniformly learnable but not PAC learnable.
Construct a class H2 of functions from the unit interval (0, 1] to {0,1} that
is not nonuniformly learnable.

6. In this question we wish to show that the algorithm Memorize is a consistent

learner for every class of (binary-valued) functions over any countable domain.

Let 4 be a countable domain and let D be a probability distribution over V.

1.

2.

Let {x; : i € N} be an enumeration of the elements of ¥ so that for all
i<j, D({xi}) < D({x;}). Prove that

Jin DP Ue) =o

i>n

Given any ¢ > 0 prove that there exists €p > 0 such that

D({a € &: D({x}) < ep}) <e.

3.

7.8 Exercises 99

Prove that for every 7 > 0, if n is such that D({2;}) < 7 for alli > n, then
for every m € N,

sopm (Bx; : (D({ai}) > 9 and x; ¢ S)] <ne7””.

Conclude that if VY is countable then for every probability distribution D
over X there exists a function mp : (0,1) x (0,1) + N such that for every
6,0 > 0 if m > mp(e,6) then

gpm Pla i € S}) > <6.
Prove that Memorize is a consistent learner for every class of (binary-
valued) functions over any countable domain.

The Runtime of Learning

So far in the book we have studied t

how

many samples are needed for

he statistical perspective of learning, namely,
earning. In other words, we focused on the

amount of information learning requires. However, when considering automated

learning, computational resources al

so play a major role in determining the com-

plexity of a task: that is, how much computation is involved in carrying out a

learning task. Once a sufficient training sample is available to the learner, there

is some computation to be done to extract a hypothesis or figure out the label of

a given test instance. These compu

ational resources are crucial in any practical

application of machine learning. We refer to these two types of resources as the

sample complexity and the comput.
our attention to the computational

The computational complexity o:

text

been extensively investigated; see,

of the computational complexi

ational complexity. In this chapter, we turn
complexity of learning.

learning should be viewed in the wider con-

y of general algorithmic tasks. This area has
for example, (Sipser 2006). The introductory

comments that follow summarize the basic ideas of that general theory that are

mos

relevant to our discussion.

The actual runtime (in seconds) of an algorithm depends on the specific ma-

chine the algorithm is being implemented on (e.g., what the clock rate of the

machine’s CPU is). To avoid dependence on the specific machine, it is common

to analyze the runtime of algorithms in an asymptotic sense. For example, we

say
a lis

hat the computational complexity of the merge-sort algorithm, which sorts

of n items, is O(nlog(n)). This implies that we can implement the algo-

rithm on any machine that satisfies the requirements of some accepted abstract

model of computation, and the actual runtime in seconds will satisfy the follow-

ing: there exist constants c and no, which can depend on the actual machine,

such that, for any value of n > no, the runtime in seconds of sorting any n items

will be at most cnlog(n). It is common to use the term feasible or efficiently

computable for tasks that can be performed by an algorithm whose running time

is O(p(n)) for some polynomial function p. One should note that this type of

analysis depends on defining what is the input size n of any instance to which

the algorithm is expected to be applied. For “purely algorithmic” tasks, as dis-

cussed in the common computational complexity literature, this input size is

clearly defined; the algorithm gets an input instance, say, a list to be sorted, or

an arithmetic operation to be calculated, which has a well defined size (say, the

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

8.1

8.1 Computational Complexity of Learning 101

number of bits in its representation). For machine learning tasks, the notion of
an input size is not so clear. An algorithm aims to detect some pattern in a data
set and can only access random samples of that data.

We start the chapter by discussing this issue and define the computational
complexity of learning. For advanced students, we also provide a detailed formal
definition. We then move on to consider the computational complexity of im-
plementing the ERM rule. We first give several examples of hypothesis classes
where the ERM rule can be efficiently implemented, and then consider some

cases where, although the class is indeed efficiently learnable, ERM implemen-
tation is computationally hard. It follows that hardness of implementing ERM
does not imply hardness of learning. Finally, we briefly discuss how one can show
hardness of a given learning task, namely, that no learning algorithm can solve
it efficiently.

Computational Complexity of Learning

Recall that a learning algorithm has access to a domain of examples, Z, a hy-
pothesis class, 1, a loss function, ¢, and a training set of examples from Z that
are sampled i.id. according to an unknown distribution D. Given parameters
e, 6, the algorithm should output a hypothesis h such that with probability of
at least 1 — 0,

< mi ,
Lp(h) < min Lp(h') +e.

As mentioned before, the actual runtime of an algorithm in seconds depends on
the specific machine. To allow machine independent analysis, we use the standard
approach in computational complexity theory. First, we rely on a notion of an
abstract machine, such as a Turing machine (or a Turing machine over the reals
(Blum, Shub & Smale 1989)). Second, we analyze the runtime in an asymptotic
sense, while ignoring constant factors, thus the specific machine is not important
as long as it implements the abstract machine. Usually, the asymptote is with
respect to the size of the input to the algorithm. For example, for the merge-sort
algorithm mentioned before, we analyze the runtime as a function of the number
of items that need to be sorted.

In the context of learning algorithms, there is no clear notion of “input size.”
One might define the input size to be the size of the training set the algorithm
receives, but that would be rather pointless. If we give the algorithm a very
large number of examples, much larger than the sample complexity of the learn-
ing problem, the algorithm can simply ignore the extra examples. Therefore, a

larger training set does not make the learning problem more difficult, and, con-
sequently, the runtime available for a learning algorithm should not increase as

we increase the size of the training set. Just the same, we can still analyze the

runtime as a function of natural parameters of the problem such as the target

accuracy, the confidence of achieving that accuracy, the dimensionality of the

102

8.1.1

The Runtime of Learning

domain set, or some measures of the complexity of the hypothesis class with
which the algorithm’s output is compared.

To illustrate this, consider a learning algorithm for the task of learning axis
aligned rectangles. A specific problem of learning axis aligned rectangles is de-
rived by specifying e, 6, and the dimension of the instance space. We can define a
sequence of problems of the type “rectangles learning” by fixing «, 6 and varying
the dimension to be d = 2,3,4,.... We can also define another sequence of “rect-
angles learning” problems by fixing d, 6 and varying the target accuracy to be

One can of course choose other sequences of such problems. Once
a sequence of the problems is fixed, one can analyze the asymptotic runtime as
a function of variables of that sequence.

Before we introduce the formal definition, there is one more subtlety we need

o tackle. On the basis of the preceding, a learning algorithm can “cheat,” by

ransferring the computational burden to the output hypothesis. For example,
he algorithm can simply define the output hypothesis to be the function that
stores the training set in its memory, and whenever it gets a test example x
it calculates the ERM hypothesis on the training set and applies it on x. Note

hat in this case, our algorithm has a fixed output (namely, the function that
we have just described) and can run in constant time. However, learning is still
hard — the hardness is now in implementing the output classifier to obtain a
abel prediction. To prevent this “cheating,” we shall require that the output of
a learning algorithm must be applied to predict the label of a new example in

ime that does not exceed the runtime of training (that is, computing the output

classifier from the input training sample). In the next subsection the advanced

reader may find a formal definition of the computational complexity of learning.

Formal Definition*

The definition that follows relies on a notion of an underlying abstract machine,
which is usually either a Turing machine or a Turing machine over the reals. We
will measure the computational complexity of an algorithm using the number of
“operations” it needs to perform, where we assume that for any machine that

implements the underlying abstract machine there exists a constant c such that
any such “operation” can be performed on the machine using c seconds.

DEFINITION 8.1 (The Computational Complexity of a Learning Algorithm)
We define the complexity of learning in two steps. First we consider the compu-
tational complexity of a fixed learning problem (determined by a triplet (Z, H, 0)
—a domain set, a benchmark hypothesis class, and a loss function). Then, in the
second step we consider the rate of change of that complexity along a sequence
of such tasks.
1. Given a function f : (0,1)? > N, a learning task (Z,H, @), and a learning
algorithm, A, we say that A solves the learning task in time O(f) if there
exists some constant number c, such that for every probability distribution D

8.2

8.2 Implementing the ERM Rule 103

over Z, and input e, 6 € (0,1), when A has access to samples generated iid.

by D,

e A terminates after performing at most cf(e, 5) operations

e The output of A, denoted h.4, can be applied to predict the label of a new

example while performing at most cf(e, 6) operations

e The output of A is probably approximately correct; namely, with proba-

bility of at least 1 — 6 (over the random samples A receives), Lp(ha) <

minney Lp(h’) +

2. Consider a sequence of learning problems, (Zn, Hn, ln)°21, where problem n
is defined by a domain Z,,, a hypothesis class H,,, and a loss function é.

Let A be a learning algorithm designed for solving learning problems of

this form. Given a function g : N x (0,1)? + N, we say that the runtime of
A with respect to the preceding sequence is O(g), if for all n, A solves the
problem (Zn,Hn,ln) in time O(fn), where f, : (0,1)? > N is defined by
frle,5) = g(n,€, 6).

We say that A is an efficient algorithm with respect to a sequence (Zn, Hn, ln)
if its runtime is O(p(n, 1/e,1/5)) for some polynomial p.

From this definition we see that the question whether a general learning prob-
lem can be solved efficiently depends on how it can be broken into a sequence
of specific learning problems. For example, consider the problem of learning a
finite hypothesis class. As we showed in previous chapters, the ERM rule over
H is guaranteed to (¢,6)-learn H if the number of training examples is order of
my(e,5) = log(|H|/d)/e?. Assuming that the evaluation of a hypothesis on an
example takes a constant time, it is possible to implement the ERM rule in time
O(\H| ma(e, 5)) by performing an exhaustive search over H with a training set
of size m(e,6). For any fixed finite H, the exhaustive search algorithm runs
in polynomial time. Furthermore, if we define a sequence of problems in which

|Hn| =n, then the exhaustive search is still considered to be efficient. However, if
we define a sequence of problems for which |H,,| = 2", then the sample complex-
ity is still polynomial in n but the computational complexity of the exhaustive

search algorithm grows exponentially with n (thus, rendered inefficient).

Implementing the ERM Rule

Given a hypothesis class H, the ERM, rule is maybe the most natural learning
paradigm. Furthermore, for binary classification problems we saw that if learning
is at all possible, it is possible with the ERM rule. In this section we discuss the
computational complexity of implementing the ERM rule for several hypothesis
classes.

Given a hypothesis class, #, a domain set Z, and a loss function @, the corre-
sponding ERM, rule can be defined as follows:

104

8.2.1

The Runtime of Learning

On a finite input sample S € Z” output some h € H that minimizes the empirical loss,

Ls h) = pa Dees (hs 2):

This section studies the runtime of implementing the ERM rule for several

examples of learning tasks.

Finite Classes

Limiting the hy,

othesis class to be a finite class may be considered as a reason-

ably mild restriction. For example, 1. can be the set of all predictors that can be

implemented by a C++ program written in at most 10000 bits of code. Other ex-

amples of useful finite classes are any hypothesis class that can be parameterized

by a finite num

of each of the parameters using a finite number of bits,

er of parameters, where we are satisfied with a representation

for example, the class of

axis aligned rectangles in the Euclidean space, R¢, when the parameters defining

any given rectangle are specified up to some limited

As we have shown in previous chaj

finite class is upper bounded
he realizable case and c = 2

complexity is only c(10,000 +

he empirical risk. Assuming

becomes k|H|m, where m is

>

H|clog(c|H|/5) /e°.

The linear dependence of t

problems (Zn, Hn, ln)°24 suc

at most n bits of code, then
that the exhaustive search ap

problem is one of the reasons

just focusing on finite classes.

It is important to realize

complexity has a mild depend
programs mentioned before, the number of hypotheses is 219-9? but the sample

A straightforward approach for im

by my(e,6) =
in the

og(e/6))/eF.

lementing the

h that log(|Hn|) = n,

approach yields an exponential runtime. In the exam:
is the set of functions that can be implemented by

proach is unrealistic fo:
we are dealing with o

hat the inefficiency o:

(such as the exhaustive search) does not yet imply t

pters, the sample complexity of
clog(c|H|/5)/e°, where
nonrealizable case. Therefore, the sample
lence on the size of H.

precision.
earning a
e=1lin

n the example of C++

ERM rule over a finite hy-

pothesis class is to perform an exhaustive search. That is, for each h € H we
calculate the empirical risk, Ls(h), and return a hypothesis that minimizes
hat the evaluation of ¢(h,z) on a single exam-
ple takes a constant amount of time, k, the runtime of this exhaustive search
he size of the training set. If we let m to be the
upper bound on the sample complexity mentioned, then the runtime becomes

he runtime on the size of H makes this approach
inefficient (and unrealistic) for large classes. Formally, if we define a sequence of

then the exhaustive search
le of C++ programs, if Hy,
a C++ program written in

he runtime grows exponentially with n, implying

r practical use. In fact, this
her hypothesis classes, like

classes of linear predictors, which we will encounter in the next chapter, and not

one algorithmic approach

hat no efficient ERM imple-

mentation exists. Indeed, we will show examples in which the ERM rule can be

implemented efficiently.

8.2.2

8.2 Implementing the ERM Rule 105

Axis Aligned Rectangles
Let Hn be the class of axis aligned rectangles in R”, namely,
Hn = {ha

where

bobsy) = {i if Vi, xi € [ai, bil (8.1)

0 otherwise

Efficiently Learnable in the Realizable Case

Consider implementing the ERM rule in the realizable case. That is, we are given
a training set S = (x1, y1),---,(Xm,Ym) of examples, such that there exists an
axis aligned rectangle, h € Hn, for which h(x;) = y; for all 7. Our goal is to find
such an axis aligned rectangle with a zero training error, namely, a rectangle
that is consistent with all the labels in S.

We show later that this can be done in time O(nm). Indeed, for each i € [n],
set a; = min{a; : (x,1) € S} and b; = max{a; : (x,1) € S}. In words, we take
a; to be the minimal value of the i’th coordinate of a positive example in S and
b; to be the maximal value of the i’th coordinate of a positive example in S.
It is easy to verify that the resulting rectangle has zero training error and that
the runtime of finding each a; and b; is O(m). Hence, the total runtime of this
procedure is O(nm).

Not Efficiently Learnable in the Agnostic Case
In the agnostic case, we do not assume that some hypothesis h perfectly predicts
the labels of all the examples in the training set. Our goal is therefore to find
h that minimizes the number of examples for which y; # h(x;). It turns out
that for many common hypothesis classes, including the classes of axis aligned
rectangles we consider here, solving the ERM problem in the agnostic setting is
NP-hard (and, in most cases, it is even NP-hard to find some h € H whose error
is no more than some constant c > 1 times that of the empirical risk minimizer
in H). That is, unless P = NP, there is no algorithm whose running time is
polynomial in m and n that is guaranteed to find an ERM hypothesis for these
problems (Ben-David, Eiron & Long 2003).
On the other hand, it is worthwhile noticing that, if we fix one specific hypoth-

esis class, say, axis aligned rectangles in some fixed dimension, n, then there exist
efficient learning algorithms for this class. In other words, there are successful
agnostic PAC learners that run in time polynomial in 1/e and 1/6 (but their
dependence on the dimension n is not polynomial).

To see this, recall the implementation of the ERM rule we presented for the
realizable case, from which it follows that an axis aligned rectangle is determined
by at most 2n examples. Therefore, given a training set of size m, we can per-
form an exhaustive search over all subsets of the training set of size at most 2n
examples and construct a rectangle from each such subset. Then, we can pick

106

8.2.3

The Runtime of Learning

the rectangle with the minimal training error. This procedure is guaranteed to
find an ERM hypothesis, and the runtime of the procedure is m?\). It follows
that if n is fixed, the runtime is polynomial in the sample size. This does not
contradict the aforementioned hardness result, since there we argued that unless
P=NP one cannot have an algorithm whose dependence on the dimension n is
polynomial as well.

Boolean Conjunctions

A Boolean conjunction is a mapping from ¥ = {0,1}”" to Y = {0,1} that can be
expressed as a proposition formula of the form x;, \...A aj, A7%j, A... A 7%},,
for some indices i1,...,i%,J1,---,jr € [n]. The function that such a proposition
formula defines is

h(x) = 1 ifa, =--- =a, =landa;,=---=2;,=0
0 otherwise

Let H@ be the class of all Boolean conjunctions over {0,1}". The size of HZ is
at most 3” 4 1 (since in a conjunction formula, each element of x either appears,
or appears with a negation sign, or does not appear at all, and we also have the
all negative formula). Hence, the sample complexity of learning H@ using the
ERM rule is at most nlog(3/d)/e.

Efficiently Learnable in the Realizable Case

Next, we show that it is possible to solve the ERM problem for H@ in time
polynomial in n and m. The idea is to define an ERM conjunction by including
in the hypothesis conjunction all the literals that do not contradict any positively
labeled example. Let vj,...,V)n+ be all the positively labeled instances in the
input sample S. We define, by induction on i < m*, a sequence of hypotheses
(or conjunctions). Let ho be the conjunction of all possible literals. That is,
ho = 21 A7%1 A 22 A... A 2, A 72. Note that ho assigns the label 0 to all the
elements of V. We obtain h;,1 by deleting from the conjunction h, all the literals

hat are not satisfied by v;i1. The algorithm outputs the hypothesis h,,+. Note

hat h,,+ labels positively all the positively labeled examples in S. Furthermore,
‘or every i < m*, h; is the most restrictive conjunction that labels v1,...,Vvi

positively. Now, since we consider learning in the realizable setup, there exists
a conjunction hypothesis, f € H@, that is consistent with all the examples in
S. Since h,,+ is the most restrictive conjunction that labels positively all the
positively labeled members of S, any instance labeled 0 by f is also labeled 0 by
hy»+ . It follows that h,,+ has zero training error (w.r.t. S$), and is therefore a
egal ERM hypothesis. Note that the running time of this algorithm is O(mn).


8.2.4

8.3

8.3 Efficiently Learnable, but Not by a Proper ERM 107

Not Efficiently Learnable in the Agnostic Case

As in the case of axis aligned rectangles, unless P = NP, there is no algorithm
whose running time is polynomial in m and n that guaranteed to find an ERM
hypothesis for the class of Boolean conjunctions in the unrealizable case.

Learning 3-Term DNF

We next show that a slight generalization of the class of Boolean conjunctions
leads to intractability of solving the ERM problem even in the realizable case.
Consider the class of 3-term disjunctive normal form formulae (3-term DNF).
The instance space is Y = {0,1}" and each hypothesis is represented by the
Boolean formula of the form h(x) = A1(x) V A2(x) V A3(x), where each A;(x) is
a Boolean conjunction (as defined in the previous section). The output of h(x) is
1 if either Aj(x) or Ag(x) or A3(x) outputs the label 1. If all three conjunctions
output the label 0 then h(x) = 0.

Let H3pyp be the hypothesis class of all such 3-term DNF formulae. The size

of H3. pvp is at most 3°". Hence, the sample complexity of learning H?p yp, using
the ERM rule is at most 3nlog(3/d)/e.

However, from the computational perspective, this learning problem is hard.
It has been shown (see (Pitt & Valiant 1988, Kearns et al. 1994)) that unless
RP = NP, there is no polynomial time algorithm that properly learns a sequence

i

of 3-term DNF learning problems in which the dimension of the n’th problem is
n. By “properly” we mean that the algorithm should output a hypothesis that is
a 3-term DNF formula. In particular, since ERMy”,,,,, Outputs a 3-term DNF
formula it is a proper learner and therefore it is hard to implement it. The proof
uses a reduction of the graph 3-coloring problem to the problem of PAC learning
3-term DNF. The detailed technique is given in Exercise 3. See also (Kearns &
Vazirani 1994, Section 1.4).

Efficiently Learnable, but Not by a Proper ERM

In the previous section we saw that it is impossible to implement the ERM rule
efficiently for the class H3pyp of 3-DNF formulae. In this section we show that it
is possible to learn this class efficiently, but using ERM with respect to a larger
class.

Representation Independent Learning Is Not Hard

Next we show that it is possible to learn 3-term DNF formulae efficiently. There
is no contradiction to the hardness result mentioned in the previous section as we
now allow “representation independent” learning. That is, we allow the learning
algorithm to output a hypothesis that is not a 3-term DNF formula. The ba-
sic idea is to replace the original hypothesis class of 3-term DNF formula with
a larger hypothesis class so that the new class is easily learnable. The learning

108

8.4

The Runtime of Learning

algorithm might return a hypothesis that does not belong to the original hypoth-
esis class; hence the name “representation independent” learning. We emphasize
that in most situations, returning a hypothesis with good predictive ability is
what we are really interested in doing.

We start by noting that because V distributes over /, each 3-term DNF formula
can be rewritten as

A, V Ao V Ag = \ (uVvVw)
uEA ve A2,wEe Ag

Next, let us define: w : {0,1}" > {0,1}@")” such that for each triplet of literals
u,v, w there is a variable in the range of 7) indicating if wu V v V w is true or false.
So, for each 3-DNF formula over {0,1}” there is a conjunction over {0,1}@")”,
with the same truth table. Since we assume that the data is realizable, we can
solve the ERM problem with respect to the class of conjunctions over {0, pen)*,
Furthermore, the sample complexity of learning the class of conjunctions in the

higher dimensional space is at most n° log(1/d)/e. Thus, the overall runtime of
this approach is polynomial in n.
Intuitively, the idea is as follows. We started with a hypothesis class for which

learning is hard. We switched to another representation where the hypothesis
class is larger than the original class but has more structure, which allows for a
more efficient ERM search. In the new representation, solving the ERM problem

is easy.

Hardness of Learning*

We have just demonstrated that the computational hardness of implementing
ERM, does not imply that such a class H is not learnable. How can we prove
that a learning problem is computationally hard?

One approach is to rely on cryptographic assumptions. In some sense, cryp-
tography is the opposite of learning. In learning we try to uncover some rule
underlying the examples we see, whereas in cryptography, the goal is to make
sure that nobody will be able to discover some secret, in spite of having access

to some partial information about it. On that high level intuitive sense, results
about the cryptographic security of some system translate into results about

the unlearnability

way of proving that a cryptographic protocol is not breakable. Even the common
assumption of P # NP does not suffice for that (although it can be shown to
be necessary for most common cryptographic scenarios). The common approach
for proving that cryptographic protocols are secure is to start with some cryp-
tographic assumptions. The more these are used as a basis for cryptography, the
stronger is our belief that they really hold (or, at least, that algorithms that will
refute them are hard to come by).

We now briefly describe the basic idea of how to deduce hardness of learnabil-
ity from cryptographic assumptions. Many cryptographic systems rely on the

8.4 Hardness of Learning* 109

of some corresponding task. Regrettably, currently one has no

assumption that there exists a one way function. Roughly speaking, a one way

function is a func

ion f : {0,1}” > {0,1}" (more formally, it is a sequence of

functions, one for each dimension n) that is easy to compute but is hard to in-

vert. More formally, f can be computed in time poly(n) but for any randomized

polynomial time a

where the probabi

gorithm A, and for every polynomial p(-),

P[F(AU@S))) = S09] < gn:

ity is taken over a random choice of x according to the uniform

distribution over {0,1}” and the randomness of A.

A one way func
nomial function p,
length < p(n), suc
and every x € {0,

feasible. Such func’

ated by some poly:

number of strings

f is hard to invert,

ion, f, is called trapdoor one way function if, for some poly-
for every n there exists a bit-string s, (called a secret key) of
h that there is a polynomial time algorithm that, for every n
1}”, on input (f(x), sn) outputs x. In other words, although

once one has access to its secret key, inverting f becomes
tions are parameterized by their secret key.

Now, let F,, be a family of trapdoor functions over {0,1}” that can be calcu-

nomial time algorithm. That is, we fix an algorithm that given

a secret key (representing one function in F,,) and an input vector, it calculates
he value of the function corresponding to the secret key on the input vector in
polynomial time. Consider the task of learning the class of the corresponding
inverses, H}} = {f~!: f € Fy}. Since each function in this class can be inverted
by some secret key s, of size polynomial in n, the class Hj} can be parameter-
ized by these keys and its size is at most 2?"). Its sample complexity is therefore

polynomial in n. We claim that there can be no efficient learner for this class. If
here were such a learner, L, then by sampling uniformly at random a polynomial

in {0,1}”", and computing f over them, we could generate a

abeled training sample of pairs (f(x),x), which should suffice for our learner to
figure out an (€,6) approximation of f~! (w.r.t. the uniform distribution over
he range of f), which would violate the one way property of f.

A more detailed treatment, as well as a concrete example, can be found in
(Kearns & Vazirani 1994, Chapter 6). Using reductions, they also show that


110

8.5

8.6

8.7

The Runtime of Learning

the class of functions that can be calculated by small Boolean circuits is not
efficiently learnable, even in the realizable case.

Summary

The runtime of learning algorithms is asymptotically analyzed as a function of
different parameters of the learning problem, such as the size of the hypothe-
sis class, our measure of accuracy, our measure of confidence, or the size of the
domain set. We have demonstrated cases in which the ERM rule can be imple-
mented efficiently. For example, we derived efficient algorithms for solving the
ERM problem for the class of Boolean conjunctions and the class of axis aligned
rectangles, under the realizability assumption. However, implementing ERM for
these classes in the agnostic case is NP-hard. Recall that from the statistical
perspective, there is no difference between the realizable and agnostic cases (i.e.,
a class is learnable in both cases if and only if it has a finite VC-dimension).
In contrast, as we saw, from the computational perspective the difference is im-
mense. We have also shown another example, the class of 3-term DNF, where
implementing ERM is hard even in the realizable case, yet the class is efficiently
learnable by another algorithm.

Hardness of implementing the ERM rule for several natural hypothesis classes
has motivated the development of alternative learning methods, which we will
discuss in the next part of this book.

Bibliographic Remarks

Valiant (1984) introduced the efficient PAC learning model in which the runtime
of the algorithm is required to be polynomial in 1/e, 1/5, and the representation
size of hypotheses in the class. A detailed discussion and thorough bibliographic
notes are given in Kearns & Vazirani (1994).

Exercises

1. Let H be the class of intervals on the line (formally equivalent to axis aligned
rectangles in dimension n = 1). Propose an implementation of the ERM,
learning rule (in the agnostic case) that given a training set of size m, runs
in time O(m?).

Hint: Use dynamic programming.

2. Let Hi,H2,... be a sequence of hypothesis classes for binary classification.
Assume that there is a learning algorithm that implements the ERM rule in
the realizable case such that the output hypothesis of the algorithm for each
class H,, only depends on O(n) examples out of the training set. Furthermore,

8.7 Exercises 111

assume that such a hypothesis can be calculated given these O(n) examples

in

ime O(n), and that the empirical risk of each such hypothesis can be

evaluated in time O(mn). For example, if H, is the class of axis aligned
rectangles in R”, we saw that it is possible to find an ERM hypothesis in the

realizable case that is defined by at most 2n examples. Prove that in such

cases, it is possible to find an ERM hypothesis for H,, in the unrealizable case

in time O(mnm?™).,

3. In

his exercise, we present several classes for which finding an ERM classi-

fier is computationally hard. First, we introduce the class of n-dimensional

halfspaces, HS,,, for a domain Y = R”. This is the class of all functions of

the form hw,»(x) = sign((w,x) + 6) where w,x € R", (w,x) is their inner

product, and b € R. See a detailed description in Chapter 9.

1.

Show that ERM, over the class H = HS’, of linear predictors is compu-

tationally hard. More precisely, we consider the sequence of problems in
which the dimension n grows linearly and the number of examples m is set
to be some constant times n.

Hint: You can prove the hardness by a reduction from the following prob-

lem:
Maz FS: Given a system of linear inequalities, Ax > b with A € R™*" and b €
R™ (that is, a system of m linear inequalities in n variables, x = (x1,...,2n)),

find a subsystem containing as many inequalities as possible that has a solution
(such a subsystem is called feasible).

It has been shown (Sankaran 1993) that the problem Max FS is NP-hard.
Show that any algorithm that finds an ERMys,, hypothesis for any training
sample S € (R" x {+1,—1})” can be used to solve the Max FS problem of
size m,n. Hint: Define a mapping that transforms linear inequalities in n
variables into labeled points in R”, and a mapping that transforms vectors
in R" to halfspaces, such that a vector w satisfies an inequality q if and
only if the labeled point that corresponds to q is classified correctly by the
halfspace corresponding to w. Conclude that the problem of empirical risk
minimization for halfspaces in also NP-hard (that is, if it can be solved in

time polynomial in the sample size, m, and the Euclidean dimension, n,

then every problem in the class NP can be solved in polynomial time).

. Let ¥ = R” and let H7? be the class of all intersections of k-many linear

halfspaces in R”. In this exercise, we wish to show that ERMy» is com-
putationally hard for every k > 3. Precisely, we consider a sequence of
problems where k > 3 is a constant and n grows linearly. The training set
size, m, also grows linearly with n.

Towards this goal, consider the k-coloring problem for graphs, defined as

follows:

Given a graph G = (V,£), and a number k, determine whether there exists a
function f : V > {1...k} so that for every (u,v) € E, f(u) 4 f(v).

The k-coloring problem is known to be NP-hard for every k > 3 (Karp
1972).

112

The Runtime of Learning

We wish to reduce the k-coloring problem to ERMyp: that is, to prove

that if there is an algorithm that solves the ERM» problem in time

polynomial in k, n, and the sample size m, then there is a polynomial time

algorithm for the graph k-coloring problem.

Given a graph G = (V,E), let {v1 ... vn} be
a sample $(G) € (R” x {+1})”, where m =
e For every v; € V, construct an instance e;

e For every edge (v;,v;) € E, construct an
positive label.

the vertices in V. Construct
|V| + |Z], as follows:

with a negative label.
instance (e; + e;)/2 with a

1. Prove that if there exists some h € Hj that has zero error over S(G)

then G is k-colorable.

Hint: Let h = ayani hj be an ERM classifier in Hi over S. Define a

coloring of V by setting f(v;) to be the min

imal j such that hj(e;) = —1.

Use the fact that halfspaces are convex sets to show that it cannot be

true that two vertices that are connected by an edge have the same

color.

2. Prove that if G is k-colorable then there exists some h € Hj’ that has

zero error over S(G).

Hint: Given a coloring f of the vertices of G, we should come up with k
hyperplanes, hy... hx whose intersection is a perfect classifier for S(G).
Let b = 0.6 for all of these hyperplanes and, for t < k let the i’th weight

of the ¢’th hyperplane, w;,;, be —1 if f(v:)
3. Based on the above, prove that for any k
NP-hard.

= t and 0 otherwise.
2 3, the ERMy» problem is

4. In this exercise we show that hardness of solving the ERM problem is equiv-

alent to hardness of proper PAC learning. Recall that by “properness” of the

algorithm we mean that it must output a hypothesis from the hypothesis

class. To formalize this statement, we first need

the following definition.

DEFINITION 8.2. The complexity class Randomized Polynomial (RP) time

is the class of all decision problems (that is, prob:

ems in which on any instance

one has to find out whether the answer is YES or NO) for which there exists a

probabilistic algorithm (namely, the algorithm is allowed to flip random coins

while it is running) with these properties:
e On any input instance the algorithm runs in
size.

olynomial time in the input

e Ifthe correct answer is NO, the algorithm must return NO.

e If the correct answer is YES, the algorithm r
a > 1/2 and returns NO with probability

eturns YES with probability

—a.t

Clearly the class RP contains the class P. It is also known that RP is

contained in the class NP. It is not known whether any equality holds among

these three complexity classes, but it is widely

believed that NP is strictly

1 The constant 1/2 in the definition can be replaced by any constant in (0, 1).

8.7 Exercises 113

larger than RP. In particular, it is believed that NP-hard problems cannot be
solved by a randomized polynomial time algorithm.

e Show that if a class H is properly PAC learnable by a polynomial time
algorithm, then the ERM, problem is in the class RP. In particular, this
implies that whenever the ERM, problem is NP-hard (for example, the
class of intersections of halfspaces discussed in the previous exercise),
then, unless NP = RP, there exists no polynomial time proper PAC
learning algorithm for H.
Hint: Assume you have an algorithm A that properly PAC learns a

class H in time polynomial in some class parameter n as well as in 1/e
and 1/6. Your goal is to use that algorithm as a subroutine to contract

an algorithm B for solving the ERM problem in random polynomial
time. Given a training set, S € (¥ x {+1}™), and some h € H whose
error on S' is zero, apply the PAC learning algorithm to the uniform
distribution over S and run it so that with probability > 0.3 it finds a
function h € H that has error less than € = 1/|S| (with respect to that
uniform distribution). Show that the algorithm just described satisfies

the requirements for being a RP solver for ERMy.


Part II

From Theory to Algorithms


Linear Predictors

In this chapter we will study the family of linear predictors, one of the most
useful families of hypothesis classes. Many learning algorithms that are being
widely used in practice rely on linear predictors, first and foremost because of
he ability to learn them efficiently in many cases. In addition, linear predictors
are intuitive, are easy to interpret, and fit the data reasonably well in many
natural learning problems.
We will introduce several hypothesis classes belonging to this family — halfspaces,
inear regression predictors, and logistic regression predictors — and present rele-

vant learning algorithms: linear programming and the Perceptron algorithm for
he class of halfspaces and the Least Squares algorithm for linear regression.
This chapter is focused on learning linear predictors using the ERM approach;
however, in later chapters we will see alternative paradigms for learning these

hypothesis classes.
First, we define the class of affine functions as

La = {hwy :w €R’,DER},

where

d
hw,o(x) = (w,x) +b= (x wir ) +b.

i=l

It will be convenient also to use the notation
La = {x4 (w,x) +b: w € R40 R},

which reads as follows: La is a set of functions, where each function is parame-
terized by w € R¢ and b € R, and each such function takes as input a vector x
and returns as output the scalar (w, x) + b.

The different hypothesis classes of linear predictors are compositions of a func-
tion ¢: R—> Y on Lg. For example, in binary classification, we can choose ¢ to
be the sign function, and for regression problems, where Y = R, ¢ is simply the
identity function.

It may be more convenient to incorporate b, called the bias, into w as an
extra coordinate and add an extra coordinate with a value of 1 to all x € 4;
namely, let w! = (b,wi,w2,...wa) € R¢+? and let x’ = (1,21, 22,...,2a) €

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

118

9.1

Linear Predictors

R“*1. Therefore,
hw,b(X) = (w,x) + b = (w’,x’).

Tt follows that each affine function in R? can be rewritten as a homogenous linear
function in R¢+! applied over the transformation that appends the constant 1
to each input vector. Therefore, whenever it simplifies the presentation, we will
omit the bias term and refer to Lq as the class of homogenous linear functions
of the form hy (x) = (w,x).

Throughout the book we often use the general term “linear functions” for both
affine functions and (homogenous) linear functions.

Halfspaces

The first hypothesis class we consider is the class of halfspaces, designed for
binary classification problems, namely, 4 = R¢ and Y = {—1,+1}. The class of
halfspaces is defined as follows:

HSq = signo La = {x 4 sign(hw,(X)) : hw,o € La}.

In other words, each halfspace hypothesis in HSq is parameterized by w €
R¢ and b € R and upon receiving a vector x the hypothesis returns the label
sign((w, x) + 0).

To illustrate this hypothesis class geometrically, it is instructive to consider
he case d = 2. Each hypothesis forms a hyperplane that is perpendicular to the
vector w and intersects the vertical axis at the point (0,—b/w2). The instances

hat are “above” the hyperplane, that is, share an acute angle with w, are labeled

positively. Instances that are “below” the hyperplane, that is, share an obtuse
angle with w, are labeled negatively.

w + 7

In Section 9.1.3 we will show that VCdim(HSz) = d+ 1. It follows that we
can learn halfspaces using the ERM paradigm, as long as the sample size is
Q (2). Therefore, we now discuss how to implement an ERM procedure
for halfspaces.

We introduce below two solutions to finding an ERM halfspace in the realiz-
able case. In the context of halfspaces, the realizable case is often referred to as
the “separable” case, since it is possible to separate with a hyperplane all the
positive examples from all the negative examples. Implementing the ERM rule

9.1.1

9.1 Halfspaces 119

in the nonseparable case (i.e., the agnostic case) is known to be computationally
hard (Ben-David & Simon 2001). There are several approaches to learning non-
separable data. The most popular one is to use surrogate loss functions, namely,
to learn a halfspace that does not necessarily minimize the empirical risk with
the 0 — 1 loss, but rather with respect to a diffferent loss function. For example,

in Section 9.3 we will describe the logistic regression approach, which can be
implemented efficiently even in the nonseparable case. We will study surrogate
loss functions in more detail later on in Chapter 12.

Linear Programming for the Class of Halfspaces

Linear programs (LP) are problems that can be expressed as maximizing a linear
function subject to linear inequalities. That is,

max (u, w)

werk?

subject to Aw>v

where w € R? is the vector of variables we wish to determine, A is an m x
d matrix, and v € R™,u € R®@ are vectors. Linear programs can be solved
efficiently,' and furthermore, there are publicly available implementations of LP
solvers.

We will show that the ERM problem for halfspaces in the realizable case can
be expressed as a linear program. For simplicity, we assume the homogenous
case. Let S = {(xi,yi)}721 be a training set of size m. Since we assume the
realizable case, an ERM predictor should have zero errors on the training set.
That is, we are looking for some vector w € R¢ for which

sign((w, x;)) = yi, Vi =1,...,m.

Equivalently, we are looking for some vector w for which

yi(w,x;) > 0, Vi=1,...,m.
Let w* be a vector that satisfies this condition (it must exist since we assume
realizability). Define 7 = min;(y;(w*,x;)) and let w = “. Therefore, for all i

we have

1
YyilW, vi) = 7 Yi(w" xi) 21.

We have thus shown that there exists a vector that satisfies
yi(w,xi) > 1, Vi =1,...,m. (9.1)

And clearly, such a vector is an ERM predictor.
To find a vector that satisfies Equation (9.1) we can rely on an LP solver as

follows. Set A to be the m x d matrix whose rows are the instances multiplied

1 Namely, in time polynomial in m, d, and in the representation size of real numbers.

120

9.1.2

Linear Predictors

by yj. That is, Aj; = yi vi,7, where aj; is the j’th element of the vector x;. Let
v be the vector (1,...,1) € R”. Then, Equation (9.1) can be rewritten as

Aw >v.

The LP form requires a maximization objective, yet all the w that satisfy the
constraints are equal candidates as output hypotheses. Thus, we set a “dummy”
objective, u = (0,..., 0) eR?

Perceptron for Halfspaces

A different implementation of the ERM rule is the Perceptron algorithm of
Rosenblatt (Rosenblatt 1958). The Perceptron is an iterative algorithm that
constructs a sequence of vectors w),w®),.... Initially, w™ is set to be the
all-zeros vector. At iteration t, the Perceptron finds an example i that is mis-
labeled by w“), namely, an example for which sign((w“),x;)) 4 y;. Then, the
Perceptron updates w\) by adding to it the instance x; scaled by the label y;.
That is, wt) = wh 4 yix;. Recall that our goal is to have y;(w,x;) > 0 for
all i and note that

yi(wlD 2x5) = yw + yixixi) = yi(w, xi) + |lcll?.

ial

ence, the update of the Perceptron guides the solution to be “more correct” on

ct

he i’th example.

Batch Perceptron

input: A training set (x1, y1),.--,(Km;Ym)
initialize: w') = (0,...,0)
for t=1,2,...

if (37 s.t. y(w,x;) < 0) then
wt!) = wl!) + yx;

else
output w!)

The following theorem guarantees that in the realizable case, the algorithm
stops with all sample points correctly classified.

THEOREM 9.1 Assume that (x1,41),..-, (Xm; Ym) ts separable, let B = min{||w]| :
Vi € [m],  yi(w,x:) > 1}, and let R = max; ||x;||. Then, the Perceptron al-
gorithm stops after at most (RB)? iterations, and when it stops it holds that
Vie [m], y(w,x,) > 0.

Proof By the definition of the stopping condition, if the Perceptron stops it
must have separated all the examples. We will show that if the Perceptron runs
for T iterations, then we must have T < (RB), which implies the Perceptron
must stop after at most (RB)? iterations.

Let w* be a vector that achieves the minimum in the definition of B. That is,

9.1 Halfspaces 121

yi(w*,x;) > 1 for all i, and among all vectors that satisfy these constraints, w*
is of minimal norm.

The idea of the proof is to show that after performing T iterations, the cosine
of the angle between w* and w‘T +) is at least yr. That is, we will show that

(w*, w(T+)) VP

a a ans 2
[wr] [wT] > RB 02)

By the Cauchy-Schwartz inequality, the left-hand side of Equation (9.2) is at
most 1. Therefore, Equation (9.2) would imply that

vT 2
1> RE => T<(RB)’,
which will conclude our proof.

To show that Equation (9.2) holds, we first show that (w*,w7%+)) > 7.
Indeed, at the first iteration, w“) = (0,...,0) and therefore (w*,w')) = 0,
while on iteration t, if we update using example (x;, y;) we have that

(w*, wD) — Cw, wl) = (we, wtD — wl)

= (w*, yiXi) = yi(W",X;)
>1.

Therefore, after performing T iterations, we get:

(w*, wtD) = > (wr wi) - (w*,w()) >T, (9.3)

t=1

as required.
Next, we upper bound ||w'?+))||. For each iteration t we have that

Iw D/P = |wO + yexs|?

= [wO |? + 2yi(wO x) + yi lle]?

< pw |P +R? (9.4)
where the last inequality is due to the fact that example i is necessarily such
that yi(w,x;) <0, and the norm of x; is at most R. Now, since ||w)||? = 0,
if we use Equation (9.4) recursively for T iterations, we obtain that

Jw)? < TR = Ww | < VTR. (9.5)

Combining Equation (9.3) with Equation (9.5), and using the fact that ||w*|| =
B, we obtain that

(wT +) w*) s T VT

Iwe|||weD| ~ BVTR BR’

We have thus shown that Equation (9.2) holds, and this concludes our proof.


122

9.1.3

Linear Predictors

Remark 9.1 The Perceptron is simple to implement and is guaranteed to con-
verge. However, the convergence rate depends on the parameter B, which in
some situations might be exponentially large in d. In such cases, it would be
better to implement the ERM problem by solving a linear program, as described
in the previous section. Nevertheless, for many natural data sets, the size of B
is not too large, and the Perceptron converges quite fast.

The VC Dimension of Halfspaces
To compute the VC dimension of halfspaces, we start with the homogenous case.

THEOREM 9.2. The VC dimension of the class of homogenous halfspaces in R¢
is d.

Proof First, consider the set of vectors e1,...,e@a, where for every i the vector
e; is the all zeros vector except 1 in the 2’th coordinate. This set is shattered
by the class of homogenous halfspaces. Indeed, for every labeling y,...,ya, set

w = (yi,---, Ya), and then (w,e;) = y; for all i.

Next, let x1,...,Xa41 be a set of d+1 vectors in R¢. Then, there must exist

real numbers a1,...,@a41, not all of them are zero, such that ya a;x; = 0.

Let I = {i : a; > 0} and J = {j : a; < 0}. Either J or J is nonempty. Let us
first assume that both of them are nonempty. Then,

Yax= Dla

wel jet

Now, suppose that x1,...,Xa41 are shattered by the class of homogenous classes.
Then, there must exist a vector w such that (w,x;) > 0 for all i € I while
(w,x,;) <0 for every j € J. It follows that

0< So ai(xi,w) = (x oxow) = (x |aj

i€l jel jes

o) =O |aj|(xj,w) <0,

jet

which leads to a contradiction. Finally, if J (respectively, I) is empty then the
right-most (respectively, left-most) inequality should be replaced by an equality,

which still leads to a contradiction.

THEOREM 9.3 The VC dimension of the class of nonhomogenous halfspaces in
R¢isd+l1.

Proof First, as in the proof of Theorem 9.2, it is easy to verify that the set
of vectors 0,e1,...,€a is shattered by the class of nonhomogenous halfspaces.
Second, suppose that the vectors x1,...,Xa+2 are shattered by the class of non-
homogenous halfspaces. But, using the reduction we have shown in the beginning
of this chapter, it follows that there are d+ 2 vectors in R¢+! that are shattered
by the class of homogenous halfspaces. But this contradicts Theorem 9.2.


9.2

9.2 Linear Regression 123

Figure 9.1 Linear regression for d = 1. For instance, the x-axis may denote the age of
the baby, and the y-axis her weight.

Linear Regression

Linear regression is a common statistical tool for modeling the relationship be-
tween some “explanatory” variables and some real valued outcome. Cast as a
learning problem, the domain set ¥ is a subset of R¢, for some d, and the la-
bel set Y is the set of real numbers. We would like to learn a linear function
h: R4 > R that best approximates the relationship between our variables (say,
for example, predicting the weight of a baby as a function of her age and weight
at birth). Figure 9.1 shows an example of a linear regression predictor for d = 1.

The hypothesis class of linear regression predictors is simply the set of linear
functions,

Hreg = La = {x4 (w,x) +b: w ER’, bE R}.

Next we need to define a loss function for regression. While in classification the
definition of the loss is straightforward, as ¢(h, (x, y)) simply indicates whether
h(x) correctly predicts y or not, in regression, if the baby’s weight is 3 kg, both
the predictions 3.00001 kg and 4 kg are “wrong,” but we would clearly prefer
the former over the latter. We therefore need to define how much we shall be
“penalized” for the discrepancy between h(x) and y. One common way is to use
the squared-loss function, namely,

O(h, (x,y) = (hx) — y)?.

For this loss function, the empirical risk function is called the Mean Squared
Error, namely,

m

Ls(h) = (Gx) — yi)’.

124

9.2.1

Linear Predictors

In the next subsection, we will see how to implement the ERM rule for linear
regression with respect to the squared loss. Of course, there are a variety of other
loss functions that one can use, for example, the absolute value loss function,
0(h, (x, y)) = |h(x) — y|. The ERM rule for the absolute value loss function can
be implemented using linear programming (see Exercise 1.)

Note that since linear regression is not a binary prediction task, we cannot an-
alyze its sample complexity using the VC-dimension. One

le analysis of the
sample complexity of linear regression is by relying on the “discretization trick”
(see Remark 4.1 in Chapter 4); namely, if we are happy with a representation of
each element of the vector w and the bias b using a finite number of bits (say
a 64 bits floating point representation), then the hypothesis class becomes finite
and its size is at most 244+), We can now rely on sample complexity bounds
for finite hypothesis classes as described in Chapter 4. Note, however, that to
apply the sample complexity bounds from Chapter 4 we also need that the loss
function will be bounded. Later in the book we will describe more rigorous means

to analyze the sample complexity of regression problems.

Least Squares

Least squares is the algorithm that solves the ERM problem for the hypoth-
esis class of linear regression predictors with respect to the squared loss. The
ERM problem with respect to this class, given a training set S, and using the
homogenous version of Lg, is to find

m

argmin Lg(hy) = argmin — w,x;) — yi).
gmin Ls (hw) = argn m Dl ) = yi)

To solve the problem we calculate the gradient of the objective function and
compare it to zero. That is, we need to solve

m

=U, Xi) — yi)xi = 0.

We can rewrite the problem as the problem Aw = b where

m m
A= (= Xj x!) and b= Ss YiXi- (9.6)
i=l i=l

9.2 Linear Regression 125

Or, in matrix form:

+

A=| x Xm x1 Xm (9.7)
: Yi

b=] x Xm (9.8)
: Ym

If A is invertible then the solution to the ERM problem is
w=A''b.

The case in which A is not invertible requires a few standard tools from linear
algebra, which are available in Appendix C. It can be easily shown that if the
training instances do not span the entire space of R¢ then A is not invertible.
Nevertheless, we can always find a solution to the system Aw = b because b
is in the range of A. Indeed, since A is symmetric we can write it using its
eigenvalue decomposition as A = VDV", where D is a diagonal matrix and V
is an orthonormal matrix (that is, V'V is the identity d x d matrix). Define
D* to be the diagonal matrix such that Dy, = 0 if Dj; = 0 and otherwise
D5, = 1/D;,;. Now, define

At=VD*t*V' and w=Atb.
Let v; denote the 7’th column of V. Then, we have

Aw = AA*b=VDV'VD*V'b=VDDtV'b= > viv/b.
t:Di,i AO
That is, AW is the projection of b onto the span of those vectors v; for which
D;,; # 0. Since the linear span of x1,...,Xm is the same as the linear span of
those v;, and b is in the linear span of the x;, we obtain that AW = b, which
concludes our argument.

9.2.2 Linear Regression for Polynomial Regression Tasks

Some learning tasks call for nonlinear predictors, such as polynomial predictors.
Take, for instance, a one dimensional polynomial function of degree n, that is,

n

P(x) = a9 + a1a 4 agx” bts + And

where (ao,...,@n) is a vector of coefficients of size n + 1. In the following we

depict a training set that is better fitted using a 3rd degree polynomial predictor

than using a linear predictor.

126

9.3

Linear Predictors

We will focus here on the class of one dimensional, n-degree, polynomial re-
gression predictors, namely,

where p is a one dimensional polynomial of degree n, parameterized by a vector
of coefficients (ao,...,@,). Note that ¥ = R, since this is a one dimensional
polynomial, and Y = R, as this is a regression problem.

One way to learn this class is by reduction to the problem of linear regression,
which we have already shown how to solve. To translate a polynomial regression
problem to a linear regression problem, we define the mapping 7 : R > R"+!
such that u(x) = (1,2,2”,...,2”). Then we have that

p(w(x)) = ag + ax + aga? +--+ +a,2" = (a, y(x))

and we can find the optimal vector of coefficients a by using the Least Squares
algorithm as shown earlier.

Logistic Regression

In logistic regression we learn a family of functions h from R? to the interval [0, 1].

However, logistic regression is used for classification tas
as the probability that the label of x is 1. The hypothes
logistic regression is the composition of a sigmoid function @sig : R — [0,1] over

We can interpret h(x)
class associated with

the class of linear functions La. In particular, the sigmoid function used in logistic
regression is the logistic function, defined as
1

itepey (9.9)

bsig(Z) =

The name “sigmoid” means “S-shaped,” referring to the plot of this function,
shown in the figure:


9.3 Logistic Regression 127

The hypothesis class is therefore (where for simplicity we are using homogenous
linear functions):

Heig = sig 0 La = {x +> dsig((w,x)) sw € R*}.

Note that when (w,x) is very large then @sig((w,x)) is close to 1, whereas if
(w, x) is very small then dsig((w, x)) is close to 0. Recall that the prediction of the
halfspace corresponding to a vector w is sign((w, x)). Therefore, the predictions
of the halfspace hypothesis and the logistic hypothesis are very similar whenever

|(w, x)| is large. However, when |(w, x)| is close to 0 we have that @sig((w, x)) ©
3. Intuitively, the logistic hypothesis is not sure about the value of the label so it
guesses that the label is sign((w,x)) with probability slightly larger than 50%.
In contrast, the halfspace hypothesis always outputs a deterministic prediction
of either 1 or —1, even if |(w,x)| is very close to 0.

Next, we need to specify a loss function. That is, we should define how bad it

is to predict some hw(x) € [0,1] given that the true label is y € {+1}. Clearly,

we would like that hw(x) would be large if y = 1 and that 1 — hy,(x) (ie., the
probability of predicting —1) would be large if y = —1. Note that

1- 1 exp(—(w, x)) 1
1+exp(—(w,x))  1+exp(—(w,x)) 1+ exp((w,x))

1— hw(x)

Therefore, any reasonable loss function would increase monotonically with Trespass)
or equivalently, would increase monotonically with 1 + exp(—y(w,x)). The lo-
gistic loss function used in logistic regression penalizes hy based on the log of

1+ exp(—y(w, x)) (recall that log is a monotonic function). That is,
U(hw, (x, y)) = log (1 + exp(—y(w,x))) .

Therefore, given a training set S = (x1,y1),---,(Xm,Ym), the ERM problem
associated with logistic regression is

m

1
argmin — y log (1 + exp(—yi(w, xi))) - (9.10)
wert MoT

The advantage of the logistic loss function is that it is a conver function with
respect to w; hence the ERM problem can be solved efficiently using standard
methods. We will study how to learn with convex functions, and in particular
specify a simple algorithm for minimizing convex functions, in later chapters.

The ERM problem associated with logistic regression (Equation (9.10)) is iden-
tical to the problem of finding a Maximum Likelihood Estimator, a well-known
statistical approach for finding the parameters that maximize the joint probabil-
ity of a given data set assuming a specific parametric probability function. We
will study the Maximum Likelihood approach in Chapter 24.

128

9.4

9.5

9.6

Linear Predictors

Summary

The family of linear predictors is one of the most useful families of hypothesis
classes, and many learning algorithms that are being widely used in practice
rely on linear predictors. We have shown efficient algorithms for learning linear
predictors with respect to the zero-one loss in the separable case and with respect
to the squared and logistic losses in the unrealizable case. In later chapters we
will present the properties of the loss function that enable efficient learning.
Naturally, linear predictors are effective whenever we assume, as prior knowl-
edge, that some linear predictor attains low risk with respect to the underlying
distribution. In the next chapter we show how to construct nonlinear predictors
by composing linear predictors on top of simple classes. This will enable us to

employ linear predictors for a variety of prior knowledge assumptions.

Bibliographic Remarks

The Perceptron algorithm dates back to Rosenblatt (1958). The proof of its
convergence rate is due to (Agmon 1954, Novikoff 1962). Least Squares regression
goes back to Gauss (1795), Legendre (1805), and Adrain (1808).

Exercises

1. Show how to cast the ERM problem of linear regression with respect to the
absolute value loss function, ¢(h,(x,y)) = |h(x) — y|, as a linear program;
namely, show how to write the problem

m

min l(w, xi) — yi|
w
i=l

as a linear program.
Hint: Start with proving that for any c € R,

lc] = mina st. c<aandc>-—a.
a>0

2. Show that the matrix A defined in Equation (9.6) is invertible if and only if
X1,...,Xm span R?.

3. Show that Theorem 9.1 is tight in the following sense: For any positive integer
m, there exist a vector w* € R@ (for some appropriate d) and a sequence of
examples {(x1,y1),---,(Xm;Ym)} such that the following hold:

e R=max; ||x;|| < 1.
@ ||w*|/? =m, and for alli < m, y;(x;, w*) > 1. Note that, using the notation

in Theorem 9.1, we therefore get

B=min{||w|| : Vi € [m], y:(w, aj) > 1} < Vim.

on

9.6 Exercises 129

Thus, (BR)? < m.

e When running the Perceptron on this sequence of examples it makes m
updates before converging.

Hint: Choose d = m and for every i choose x; = e;.

. (*) Given any number m, find an example of a sequence of labeled examples

((%1,Y1);+++>(XmsYm)) € (R® x {-1,+1})™ on which the upper bound of
Theorem 9.1 equals m and the perceptron algorithm is bound to make m
mistakes.

Hint: Set each x; to be a third dimensional vector of the form (a, b, y;), where
a? +b? = R? — 1. Let w* be the vector (0,0,1). Now, go over the proof of
the Perceptron’s upper bound (Theorem 9.1), see where we used inequalities
(<) rather than equalities (=), and figure out scenarios where the inequality
actually holds with equality.

. Suppose we modify the Perceptron algorithm as follows: In the update step,

instead of performing w+) = w + y;x; whenever we make a mistake, we
perform w+) = w) + ny;x; for some 7 > 0. Prove that the modified Per-
ceptron will perform the same number of iterations as the vanilla Perceptron

and will converge to a vector that points to the same direction as the output
of the vanilla Perceptron.

. In this problem, we will get bounds on the VC-dimension of the class of

(closed) balls in R¢, that is,

Ba = {Byp iv Ror> 0},

where
1 if||x—vl| <r
0 otherwise :

Bu n(x) = {

1. Consider the mapping ¢ : R¢ + R¢*++ defined by ¢(x) = (x, ||x||?). Show
that if x1,...,Xm are shattered by By then $(x1),...,¢(Xm) are shattered
by the class of halfspaces in R?*+ (in this question we assume that sign(0) =
1). What does this tell us about VCdim(Bz)?

2. (*) Find a set of d+1 points in R¢ that is shattered by By. Conclude that

d+1< VCdim(Ba) < d+ 2.

10

Boosting

Boosting is an algorithmic paradigm that grew out of a theoretical question and

became a very practical machine learning tool. The boosting approach uses a

generalization of linear predictors to address two major issues that have been

raised earlier in the book. The first is the bias-complexity tradeoff. We have

seen (in Chapter 5) that the error of an ERM learner can be decomposed into

a sum of approximation error and estimation error. The more expressive the

hypothesis class the learner is searching over, the smaller the approximation

error is, but the larger the estimation error becomes. A learner is thus faced with

the problem of picking a good tradeoff between these two considerations. The

boosting paradigm allows the learner to have smooth control over this tradeoff.

The learning starts with a basic class (that might have a large approximation

error), and as it progresses the class that the predictor may belong to grows

richer.

The second issue that boosting addresses is the computationa.
learning. As seen in Chapter 8, for many interesting concept c'
of finding an ERM hypothesis may be computationally infeasib.

complexity of
asses the task
le. A boosting

algorithm amplifies the accuracy of weak learners. Intuitively, one can think of

a weak learner as an algorithm that uses a simple “

hypothesis that comes from an easy-to-learn hypothesis class an
slightly better than a random guess. When a weak learner can
efficiently, boosting provides a tool for aggregating such weak

approximate gradually good predictors for larger, and

In this chapter we will describe and analyze a practically useful
rithm, AdaBoost (a shorthand for Adaptive Boosting).
outputs a hypothesis that is a linear combination of simple hypot.

words, AdaBoost relies on the family of hypothesis classes obtaine:

‘rule of thuml

harder to

The AdaBi

b” to output a
performs just

be implemented

hypotheses to
earn, classes.

boosting algo-
‘oost algorithm
heses. In other

by composing

a linear predictor on top of simple classes. We will show that AdaBoost enables
us to control the tradeoff between the approximation and estimation errors by

varying a single parameter.

AdaBoost demonstrates a general theme, that will recur

ater in the book, of

expanding the expressiveness of linear predictors by composing them on top of

other functions. This will be elaborated in Section 10.3.

AdaBoost stemmed from the theoretical question of whether an efficient weak

learner can be “boosted” into an efficient strong learner. This question was raised

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.
Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

10.1

10.1 Weak Learnability 131

by Kearns and Valiant in 1988 and solved in 1990 by Robert Schapire, then
a graduate student at MIT. However, the proposed mechanism was not very
practical. In 1995, Robert Schapire and Yoav Freund proposed the AdaBoost
algorithm, which was the first truly practical implementation of boosting. This
simple and elegant algorithm became hugely popular, and Freund and Schapire’s
work has been recognized by numerous awards.

Furthermore, boosting is a great example for the practical impact of learning
theory. While boosting originated as a purely theoretical problem, it has led to
popular and widely used algorithms. Indeed, as we shall demonstrate later in
this chapter, AdaBoost has been successfully used for learning to detect faces in
images.

Weak Learnability

Recall the definition of PAC learning given in Chapter 3: A hypothesis class,
H, is PAC learnable if there exist my : (0,1)? > N and a learning algorithm
with the following property: For every ¢,6 € (0,1), for every distribution D over

&, and for every labeling function f : ¥ > {+1}, if the realizable assumption
holds with respect to H,D, f, then when running the learning algorithm on
m > my(e,5) iid. examples generated by D and labeled by f, the algorithm
returns a hypothesis h such that, with probability of at least 1—4, Lip, ,)(h) < €.

Furthermore, the fundamental theorem of learning theory (Theorem 6.8 in
Chapter 6) characterizes the family of learnable classes and states that every PAC

earnable class can be learned using any ERM algorithm. However, the definition
of PAC learning and the fundamental theorem of learning theory ignores the
computational aspect of learning. Indeed, as we have shown in Chapter 8, there

are cases in which implementing the ERM rule is computationally hard (even in
he realizable case).

However, perhaps we can trade computational hardness with the requirement

for accuracy. Given a distribution D and a target labeling function f, maybe there
exists an efficiently computable learning algorithm whose error is just slightly

better than a random guess? This motivates the following definition.

DEFINITION 10.1 (y-Weak-Learnability)

e A learning algorithm, A, is a y-weak-learner for a class H if there exists a func-

tion my : (0,1) + N such that for every 6 € (0,1), for every distribution
D over #, and for every labeling function f : Y > {+1}, if the realizable
assumption holds with respect to H,D, f, then when running the learning

algorithm on m > m7(06) i.i.d. examples generated by D and labeled by f,

the algorithm returns a hypothesis h such that, with probability of at least
1-6, Lio, py(h) < 1/2 -7.

e A hypothesis class H is 7-weak-learnable if there exists a y-weak-learner for
that class.


132

Boosting

This definition is almost identical to the definition of PAC learning, which
here we will call strong learning, with one crucial difference: Strong learnability

implies the ability to find an arbitrarily good classifier (with error rate at most
€ for an arbitrarily small ¢ > 0). In weak learnability, however, we only need to

output a hypothesis whose error rate is at most 1/2 — y, namely, whose error

rate is slightly better than what a random labeling would give us. The hope is

that it may be easier to come up with efficient weak learners than with efficient

(full) PAC learners.

The fundamental theorem of learning (Theorem 6.8) states that if a hypothesis
class H has a VC dimension d, then the sample complexity of PAC learning H.

satisfies m(e,6) > Cy Hees) where C; is a constant. App

ying this with

€ = 1/2—7 we immediately obtain that if d = oo then H is not 7-weak-learnable.

This implies that from the statistical perspective (i.e., if we ignore
complexity), weak learnability is also characterized by the VC
and therefore is just as hard as PAC (strong) learning. Howeve:

computational
imension of H.
rt, when we do

consider computational complexity, the potential advantage of weak learning is

that maybe there is an algorithm that satisfies the requirements o:

and can be implemented efficiently.

weak learning

One possible approach is to take a “simple” hypothesis class, denoted B, and

to apply ERM with respect to B as the weak learning algorithm. For this to

work, we need that B will satisfy two requirements:

e ERMsg is efficiently implementable.

e For every sample that is labeled by some hypothesis from H, any ERMg

hypothesis will have an error of at most 1/2 — 7.

Then, the immediate question is whether we can boost an efficient weak learner

into an efficient strong learner. In the next section we will show that this is

indeed possible, but before that, let us show an example in which efficient weak

learnability of a class H is possible using a base hypothesis class B.

Example 10.1 (Weak Learning of 3-Piece Classifiers Using Decision Stumps)
Let © = R and let H be the class of 3-piece classifiers, namely, H = {ho,,6,,p :

01,02 € R,0, < 0,b € {£1}}, where for every x,

+b ifa<0, orxz>
—b if0,<a@<b&

he, 62,0(%) = {

An example hypothesis (for b = 1) is illustrated as follows:

+ - +

1 02

Let B be the class of Decision Stumps, that is, B = {x +> sign(a—6)-b: 0€
R,b € {+1}}. In the following we show that ERMz is a y-weak learner for H,

for y = 1/12.

10.1.1

10.1 Weak Learnability 133

To see that, we first show that for every distribution that is consistent with
H, there exists a decision stump with Lp(h) < 1/3. Indeed, just note that
every classifier in H consists of three regions (two unbounded rays and a center
interval) with alternate labels. For any pair of such regions, there exists a decision
stump that agrees with the labeling of these two components. Note that for every
distribution D over R and every partitioning of the line into three such regions,
one of these regions must have D-weight of at most 1/3. Let h € H be a zero
error hypothesis. A decision stump that disagrees with h only on such a region
has an error of at most 1/3.

Finally, since the VC-dimension of decision stumps is 2, if the sample size is
greater than ((log(1/d)/e?), then with probability of at least 1 — 6, the ERMp
rule returns a hypothesis with an error of at most 1/3 + €. Setting « = 1/12 we
obtain that the error of ERMzg is at most 1/3 + 1/12 = 1/2 — 1/12.

We see that ERMz, is a 7-weak learner for H. We next show how to implement
the ERM rule efficiently for decision stumps.

Efficient Implementation of ERM for Decision Stumps

Let Y = R@ and consider the base hypothesis class of decision stumps over R?,
namely,

Hps = {x sign(@— 2;)-b: 0€R,i€ [d],b € {+1}}.
For simplicity, assume that b = 1; that is, we focus on all the hypotheses in
Hps of the form sign(@ — x;). Let S = ((x1,41),---;(Xm+Ym)) be a training set.

We will show how to implement an ERM rule, namely, how to find a decision
stump that minimizes Ls(h). Furthermore, since in the next section we will
show that AdaBoost requires finding a hypothesis with a small risk relative to
some distribution over S, we will show here how to minimize such risk functions.
Concretely, let D be a probability vector in R™ (that is, all elements of D are
nonnegative and )>, D; = 1). The weak learner we describe later receives D and
S and outputs a decision stump h: ¥ > Y that minimizes the risk w.r.t. D,

m

Lo(h) = 0 Diltncey Zui)
i=l

Note that if D = (1/m,...,1/m) then Lp(h) = Lg(h).
Recall that each decision stump is parameterized by an index j € [d] and a
threshold 6. Therefore, minimizing Lp(h) amounts to solving the problem

min min | S> Dilly, sq + SY) Dilte,,<o | - (10.1)
jeld) OCR \ iy

Fix j € [d] and let us sort the examples so that Uj S25 S... < Xm,j. Define
0; = (tees si | [m—- 1} UL(a1j — 1), (emg +}. Note that for any 9 R
there exists 6’ € ©; that yields the same predictions for the sample S' as the

134

10.2

Boosting

threshold 9. Therefore, instead of minimizing over 9 € R we can minimize over
0€0;.

This already gives us an efficient procedure: Choose j € [d] and @ € 9; that
minimize the objective value of Equation (10.1). For every j and @ € ©; we
have to calculate a sum over m examples; therefore the runtime of this approach
would be O(dm?). We next show a simple trick that enables us to minimize the
objective in time O(dm).

The observation is as follows. Suppose we have calculated the objective for
0 € (a1
OW € (a 5,0

x;,;)- Let F(@) be the value of the objective. Then, when we consider

i+1,j) we have that

F(6') = F(9) = Diliy,=1 + Dilfy,=—1] = F(P) — yiDi-
Therefore, we can calculate the objective at 6’ in a constant time, given the
objective at the previous threshold, 6. It follows that after a preprocessing step
in which we sort the examples with respect to each coordinate, the minimization
problem can be performed in time O(dm). This yields the following pseudocode.

ERM for Decision Stumps
input:
training set S = (x1,41),---;(Km,Ym)
distribution vector D
goal: Find j*,6* that solve Equation (10.1)
initialize: F* = co

sort S using the j’th coordinate, and denote

def
U1,5 S25 S00 S$ Wmyj S Um41,5 = Img +1

F = Vig ai Di

if F < F*
FEF, OH =41;-1, 7% =5

fori =1,...,m

FPH=F-yDi

if F < F* and a5 A ti41,5
Fr=F, 0 =3(: j

output j*,0*

AdaBoost

AdaBoost (short for Adaptive Boosting) is an algorithm that has access to a
weak learner and finds a hypothesis with a low empirical risk. The AdaBoost
(Xm; Ym)
where for each i, y; = f(x;) for some labeling function f. The boosting process

algorithm receives as input a training set of examples S = (x1, y1),-

proceeds in a sequence of consecutive rounds. At round t, the booster first defines

10.2 AdaBoost 135

a distribution over the examples in S$, denoted D™. That is, DY € RY? and
an Do = 1. Then, the booster passes the distribution D“ and the sample S'
to the weak learner. (That way, the weak learner can construct i.i.d. examples
according to D and f.) The weak learner is assumed to return a “weak”
hypothesis, h;, whose error,

m

def def
e = Lpw (he) = yp Winx.) Zuid

is at most $-7 (of course, there is a probability of at most 6 that the weak learner
fails). Then, AdaBoost assigns a weight for h, as follows: w, = } log (2 —1).
That is, the weight of h; is inversely proportional to the error of h;. At the end
of the round, AdaBoost updates the distribution so that examples on which h;
errs will get a higher probability mass while examples on which h, is correct will
get a lower probability mass. Intuitively, this will force the weak learner to focus
on the problematic examples in the next round. The output of the AdaBoost
algorithm is a “strong” classifier that is based on a weighted sum of all the weak
hypotheses. The pseudocode of AdaBoost is presented in the following.

AdaBoost

input:
training set S = (x1,41),---,(Xm+Ym)
weak learner WL
number of rounds T
initialize D =(4,...,4).
fort=1,...,T:
invoke weak learner h, = WL(D™, S$
compute €, = 0771 Do Why; Ahi (xs)
let w= 3 log (2 -1

pit) DI expl— weyihe (xi)
i

for alli=1,..., m
D© exp(—weyshe(x;)) pees

update

jet

output the hypothesis h.(x) = sign (oh wyhe(x))

The following theorem shows that the training error of the output hypothesis
decreases exponentially fast with the number of boosting rounds.

THEOREM 10.2 Let S be a training set and assume that at each iteration of
AdaBoost, the weak learner returns a hypothesis for which e, < 1/2 —. Then,
the training error of the output hypothesis of AdaBoost is at most

m

1
Ls(he) = =) Mn .ceozu) S exp(-27°T) «

i=1

Proof For each t, denote f; = Up<t Wphp. Therefore, the output of AdaBoost

136

Boosting

is fr. In addition, denote

12
Z,=— o Vi fe (wi) |
=e

i=1
Note that for any hypothesis we have that Ij,(2)4y) < e¥(*), Therefore, Ls (fr) <
Zr, so it suffices to show that Zp < e27T To upper bound Zr we rewrite it
as
Zr 4r ar a
Zo Zr1 LZr-2 Z, Zo

Zp = (10.2)
where we used the fact that Z) = 1 because fp = 0. Therefore, it suffices to show
that for every round ¢,

Zit1

Za

2

<2,

(10.3)

To do so, we first note that using a simple inductive argument, for all t and 7,
envi fe (ai)

er whe)

ptt) =

Hence,

Zita oe uifen es)

4 x e~ yi fe(@)

j=l
at ete (ti) e—Yiwerrhesi (ei)
i=

™m

en Ys Se (a5)
1

j
m

= S DEFY e-yswesrahesa (es)
i=l
— pow (t+1) wepa (t+1)
=e Ss D; +e" D;
iunhea(es)=1 i:yihesi @i)=—1
=e M1 — ery) Fehr ey

1
Se (1 - ti) + V1 — 1 tt

V1/esi—1

= 2V/er4i (1 — 441).

By our assumption, €41 < 3 — 7. Since the function g(a) = a(1 — a) is mono-
tonically increasing in [0, 1/2], we obtain that

aval =en) <2 (5-7) ($47) = vIn we

10.3

10.3 Linear Combinations of Base Hypotheses 137

Finally, using the inequality 1 — a < e~* we have that \/1 — 47? < e479 /2 =

2
e277

. This shows that Equation (10.3) holds and thus concludes our proof.

Each iteration of AdaBoost involves O(m) operations as well as a single call to

he weak learner. Therefore, if the weak learner can be implemented efficiently

(as happens in the case of ERM with respect to decision stumps) then the total
raining process will be efficient.
Remark 10.2 Theorem 10.2 assumes that at each iteration of AdaBoost, the
weak learner returns a hypothesis with weighted sample error of at most 1/2—7.
According to the definition of a weak learner, it can fail with probability 4. Using
he union bound, the probability that the weak learner will not fail at all of the

iterations is at least 1 — 6T. As we show in Exercise 1, the dependence of the
sample complexity on 6 can always be logarithmic in 1/6, and therefore invoking
he weak learner with a very small 6 is not problematic. We can therefore assume
hat dT is also small. Furthermore, since the weak learner is only applied with

distributions over the training set, in many cases we can implement the weak
earner so that it will have a zero probability of failure (i.c., 6 = 0). This is the
case, for example, in the weak learner that finds the minimum value of Lp(h)
for decision stumps, as described in the previous section.

Theorem 10.2 tells us that the empirical risk of the hypothesis constructed by
AdaBoost goes to zero as T grows. However, what we really care about is the

rue risk of the output hypothesis. To argue about the true risk, we note that the
output of AdaBoost is in fact a composition of a halfspace over the predictions
of the T weak hypotheses constructed by the weak learner. In the next section
we show that if the weak hypotheses come from a base hypothesis class of low

VC-dimension, then the estimation error of AdaBoost will be small; namely, the
true risk of the output of AdaBoost would not be very far from its empirical risk.

Linear Combinations of Base Hypotheses

As mentioned previously, a popular approach for constructing a weak learner
is to apply the ERM rule with respect to a base hypothesis class (e.g., ERM
over decision stumps). We have also seen that boosting outputs a composition
of a halfspace over the predictions of the weak hypotheses. Therefore, given a
base hypothesis class B (e.g., decision stumps), the output of AdaBoost will be
a member of the following class:
T
L(B,T) = (* + sign (= wits) :weR’, Vt, he o} : (10.4)
t=1
That is, each h € L(B,T) is parameterized by T base hypotheses from B and
by a vector w € R?. The prediction of such an h on an instance x is ob-
tained by first applying the T’ base hypotheses to construct the vector w(x) =

138

Boosting

(hi(z),...,hr(x)) € RT, and then applying the (homogenous) halfspace defined
by w on 7(z).

In this section we analyze the estimation error of L(B,T) by bounding the
VC-dimension of L(B,T) in terms of the VC-dimension of B and T. We will
show that, up to logarithmic factors, the VC-dimension of L(B,T) is bounded
by T times the VC-dimension of B. It follows that the estimation error of Ad-
aBoost grows linearly with T. On the other hand, the empirical risk of AdaBoost
decreases with T’. In fact, as we demonstrate later, T can be used to decrease
he approximation error of L(B,T). Therefore, the parameter T of AdaBoost
enables us to control the bias-complexity tradeoff.
To demonstrate how the expressive power of L(B,T) increases with T, consider

he simple example, in which 4 = R and the base class is Decision Stumps,

Hpsi = {r sign(a —0)-b: 0E€R,be {+]1}}.

Note that in this one dimensional case, Hpg; is in fact equivalent to (nonho-
mogenous) halfspaces on R.

Now, let H be the rather complex class (compared to halfspaces on the line)
of piece-wise constant functions. Let g, be a piece-wise constant function with at
most r pieces; that is, there exist thresholds —co = 09 < 0; < 02 <--- <6, =0o
such that

r

Gr() = SS ailee(o.-1.6:) Vi, a; € {+1}.

i=l

Denote by G,. the class of all such piece-wise constant classifiers with at most r
pieces.
In the following we show that Gr C L(Hpsi,T); namely, the class of halfspaces
over T decision stumps yields all the piece-wise constant classifiers with at most
T pieces.
Indeed, without loss of generality consider any g € Gr with a, = (—1)'. This
implies that if x is in the interval (,-1, 6], then g(a) = (—1)!. For example:

Now, the function

T
h(x) = sign (> wy, sign(a — =) ; (10.5)

t=1

where w; = 0.5 and for t > 1, w, = (—1)', is in L(Hpsgi,T) and is equal to g
(see Exercise 2).

10.3 Linear Combinations of Base Hypotheses 139

From this example we obtain that L(Hpsi,7’) can shatter any set of T +1
instances in R; hence the VC-dimension of L(Hpsi, T) is at least T+1. Therefore,
T is a parameter that can control the bias-complexity tradeoff: Enlarging T
yields a more expressive hypothesis class but on the other hand might increase
the estimation error. In the next subsection we formally upper bound the VC-
dimension of L(B,T) for any base class B.

10.3.1 The VC-Dimension of L(B,T)

The following lemma tells us that the VC-dimension of L(B,T) is upper bounded
by O(VCdim(B) T) (the O notation ignores constants and logarithmic factors).

LEMMA 10.3 Let B be a base class and let L(B,T) be as defined in Equa-
tion (10.4). Assume that both T and VCdim(B) are at least 3. Then,

VCdim(L(B,T)) < T (VCdim(B) + 1) (3log(T (VCdim(B) + 1)) + 2).

Proof Denote d = VCdim(B). Let C = {21,...,%m} be a set that is shat-
tered by L(B,T). Each labeling of C by h € L(B,T) is obtained by first choos-
ing hi,...,hr € B and then applying a halfspace hypothesis over the vector
(hi(x),...,hr(x)). By Sauer’s lemma, there are at most (em/d)“ different di-
chotomies (i.e., labelings) induced by B over C. Therefore, we need to choose
T hypotheses, out of at most (em/d)@ different hypotheses. There are at most
(em/d)“7 ways to do it. Next, for each such choice, we apply a linear predictor,
which yields at most (em/T)? dichotomies. Therefore, the overall number of
dichotomies we can construct is upper bounded by

(em/a)*? (em/T)? < m7,

where we used the assumption that both d and T are at least 3. Since we assume
that C is shattered, we must have that the preceding is at least 2, which yields

Q” < mG,

Therefore,
(d+1)T
log(2)
Lemma A.1 in Chapter A tells us that a necessary condition for the above to
hold is that

m < log(m)

(4+ 0P, (d+0T
ms oe) 8 Togl2)

which concludes our proof. O

< (d+ 1)T(3log((d + 1)T) +2),

In Exercise 4 we show that for some base classes, B, it also holds that VCdim(L(B,T)) >
Q(VCdim(B) T).

140

10.4

Boosting

Cc D

Figure 10.1 The four types of functions, g, used by the base hypotheses for face
recognition. The value of g for type A or B is the difference between the sum of the
pixels within two rectangular regions. These regions have the same size and shape and
are horizontally or vertically adjacent. For type C, the value of g is the sum within
two outside rectangles subtracted from the sum in a center rectangle. For type D, we
compute the difference between diagonal pairs of rectangles.

AdaBoost for Face Recognition

We now turn to a base hypothesis that has been proposed by Viola and Jones for
the task of face recognition. In this task, the instance space is images, represented
as matrices of gray level values of pixels. To be concrete, let us take images of
size 24 x 24 pixels, and therefore our instance space is the set of real valued
matrices of size 24 x 24. The goal is to learn a classifier, h : ¥ > {+1}, that
given an image as input, should output whether the image is of a human face or

not.

Each hypothesis in the base class is of the form h(x) = f(g(x)), where f is a
decision stump hypothesis and g : R?+:?4 > R is a function that maps an image
to a scalar. Each function g is parameterized by

e An axis aligned rectangle R. Since each image is of size 24 x 24, there are at
most 244 axis aligned rectangles.

e A type, t € {A,B,C,D}. Each type corresponds to a mask, as depicted in

Figure 10.1.

To calculate g we stretch the mask t to fit the rectangle R and then calculate
the sum of the pixels (that is, sum of their gray level values) that lie within the
red rectangles and subtract it from the sum of pixels in the blue rectangles.
Since the number of such functions g is at most 244-4, we can implement a
weak learner for the base hypothesis class by first calculating all the possible
outputs of g on each image, and then apply the weak learner of decision stumps

described in the previous subsection. It is possible to perform the first step very

10.5

10.6

10.5 Summary 141

Figure 10.2 The first and second features selected by AdaBoost, as implemented by
Viola and Jones. The two features are shown in the top row and then overlaid on a
typical training face in the bottom row. The first feature measures the difference in
intensity between the region of the eyes and a region across the upper cheeks. The
feature capitalizes on the observation that the eye region is often darker than the
cheeks. The second feature compares the intensities in the eye regions to the intensity
across the bridge of the nose.

efficiently by a preprocessing step in which we calculate the integral image of
each image in the training set. See Exercise 5 for details.

In Figure 10.2 we depict the first two features selected by AdaBoost when
running it with the base features proposed by Viola and Jones.

Summary

Boosting is a method for amplifying the accuracy of weak learners. In this chapter
we described the AdaBoost algorithm. We have shown that after T iterations of
AdaBoost, it returns a hypothesis from the class L(B,T), obtained by composing
a linear classifier on T hypotheses from a base class B. We have demonstrated
how the parameter T controls the tradeoff between approximation and estimation
errors. In the next chapter we will study how to tune parameters such as T, based
on the data.

Bibliographic Remarks

As mentioned before, boosting stemmed from the theoretical question of whether
an efficient weak learner can be “boosted” into an efficient strong learner (Kearns
& Valiant 1988) and solved by Schapire (1990). The AdaBoost algorithm has
been proposed in Freund & Schapire (1995).

Boosting can be viewed from many perspectives. In the purely theoretical
context, AdaBoost can be interpreted as a negative result: If strong learning of
a hypothesis class is computationally hard, so is weak learning of this class. This
negative result can be useful for showing hardness of agnostic PAC learning of
a class B based on hardness of PAC learning of some other class , as long as

142

10.7

Boosting

H.

is weakly learnable using B. For example, Klivans & Sherstov (2006) have

shown that PAC learning of the class of intersection of halfspaces is hard (even

in

the realizable case). This hardness result can be used to show that agnostic

PAC learning of a single halfspace is also computationally hard (Shalev-Shwartz,
Shamir & Sridharan 2010). The idea is to show that an agnostic PAC learner

na.

ny:

in

fe)

earner for the class of intersection of halfspaces.

(von Neumann 1928), a fundamental result in game theory.

or a single halfspace can yield a weak learner for the class of intersection of

fspaces, and since such a weak learner can be boosted, we will obtain a strong

AdaBoost also shows an equivalence between the existence of a weak learner
and separability of the data using a linear classifier over the predictions of base

potheses. This result is closely related to von Neumann’s minimax theorem

AdaBoost is also related to the concept of margin, which we will study later on

Chapter 15. It can also be viewed as a forward greedy selection algorithm, a

ic that will be presented in Chapter 25. A recent book by Schapire & Freund

(2012) covers boosting from all points of view, and gives easy access to the wealth

of research that this field has produced.

Exercises

1.

Boosting the Confidence: Let A be an algorithm that guarantees the fol-
lowing: There exist some constant 59 € (0,1) and a function my : (0,1) + N
such that for every € € (0,1), if m > mz,(e) then for every distribution D it
holds that with probability of at least 1— 69, Lp(A(S)) < minney Lp(h) +e.

Suggest a procedure that relies on A and learns H in the usual agnostic
PAC learning model and has a sample complexity of

2 lath)

my (€,5) < kmy(e) + a

where
k = [log(4)/log(do)]-

Hint: Divide the data into k + 1 chunks, where each of the first k chunks
is of size mz(e) examples. Train the first k chunks using A. Argue that the
probability that for all of these chunks we have Lp(A(S)) > minnex Lp(h)+e
is at most & < 6/2. Finally, use the last chunk to choose from the k hypotheses
that A generated from the k chunks (by relying on Corollary 4.6).

Prove that the function h given in Equation (10.5) equals the piece-wise con-
stant function defined according to the same thresholds as h.

We have informally argued that the AdaBoost algorithm uses the weighting
mechanism to “force” the weak learner to focus on the problematic examples

in the next iteration. In this question we will find some rigorous justification
for this argument.

on

10.7 Exercises 143

Show that the error of h; w.r.t. the distribution D+) is exactly 1/2. That

is, show that for every t € [T]

m
t+1

SE DY thy, zeten] = 1/2.

i=l

. In this exercise we discuss the VC-dimension of classes of the form L(B,T).

We proved an upper bound of O(dT log(dT)), where d = VCdim(B). Here we
wish to prove an almost matching lower bound. However, that will not be the
case for all classes B.

1.

Note that for every class B and every number T > 1, VCdim(B) <
VCdim(L(B,T)). Find a class B for which VCdim(B) = VCdim(L(B, T))
for every T > 1.

Hint: Take ¥ to be a finite set.

. Let By be the class of decision stumps over R¢. Prove that log(d) <

VCdim(Ba) < 5 + 2log(d).

Hints:

e For the upper bound, rely on Exercise 11.

e For the lower bound, assume d = 2". Let A be a k x d matrix whose
columns are all the d binary vectors in {+1}*. The rows of A form
a set of k vectors in R’. Show that this set is shattered by decision
stumps over R¢.

Let T > 1 be any integer. Prove that VCdim(L(Bu,T)) > 0.5T log(d).

Hint: Construct a set of tk instances by taking the rows of the matrix A

from the previous question, and the rows of the matrices 2A,3A,4A,..., ZA.

Show that the resulting set is shattered by L(Ba,T).

. Efficiently Calculating the Viola and Jones Features Using an Inte-

gral Image: Let A be a 24 x 24 matrix representing an image. The integral
image of A, denoted by J(A), is the matrix B such that B;,; => A

rej sre; Aaj:

Show that (A) can be calculated from A in time linear in the size of A

Show how every Viola and Jones feature can be calculated from J(A) in a
constant amount of time (that is, the runtime does not depend on the
size of the rectangle defining the feature).

11

Model Selection and Validation

In the previous chapter we have described the AdaBoost algorithm and have
shown how the parameter T of AdaBoost controls the bias-complexity trade-
off. But, how do we set T in practice? More generally, when approaching some
practical problem, we usually can think of several algorithms that may yield a
good solution, each of which might have several parameters. How can we choose
the best algorithm for the particular problem at hand? And how do we set the
algorithm’s parameters? This task is often called model selection.

To illustrate the model selection task, consider the problem of learning a one
dimensional regression function, h : R — R. Suppose that we obtain a training
set as depicted in the figure.

We can consider fitting a polynomial to the data, as described in Chapter 9.

However, we might be uncertain regarding which degree d would give the best

results for our data set: A small degree may not fit the data well (i.e., it will
have a large approximation error), whereas a high degree may lead to overfitting
(i-e., it will have a large estimation error). In the following we depict the result
of fitting a polynomial of degrees 2, 3, and 10. It is easy to see that the empirical
risk decreases as we enlarge the degree. However, looking at the graphs, our
intuition tells us that setting the degree to 3 may be better than setting it to 10.
It follows that the empirical risk alone is not enough for model selection.

egree 2 legree 3

fal

egree 10

I. Z pr WAL L_/

cy a as € SS + nd

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning


11.1

11.1 Model Selection Using SRM 145

In this chapter we will present two approaches for model selection. The first
approach is based on the Structural Risk Minimization (SRM) paradigm we
have described and analyzed in Chapter 7.2. SRM is particularly useful when
a learning algorithm depends on a parameter that controls the bias-complexity
tradeoff (such as the degree of the fitted polynomial in the preceding example
or the parameter T’ in AdaBoost). The second approach relies on the concept
of validation. The basic idea is to partition the training set into two sets. One
is used for training each of the candidate models, and the second is used for
deciding which of them yields the best results.

In model selection tasks, we try to find the right balance between approxi-
mation and estimation errors. More generally, if our learning algorithm fails to
find a predictor with a small risk, it is important to understand whether we
suffer from overfitting or underfitting. In Section 11.3 we discuss how this can
be achieved.

Model Selection Using SRM

The SRM paradigm has been described and analyzed in Section 7.2. Here we
show how SRM can be used for tuning the tradeoff between bias and complexity
without deciding on a specific hypothesis class in advance. Consider a countable
sequence of hypothesis classes H1, H2,H3,.... For example, in the problem of
polynomial regression mentioned, we can take Hg to be the set of polynomials
of degree at most d. Another example is taking Hy to be the class L(B,d) used
by AdaBoost, as described in the previous chapter.

We assume that for every d, the class Hq enjoys the uniform convergence
property (see Definition 4.3 in Chapter 4) with a sample complexity function of
the form

me (¢,6) < {A les(U/9) eet), (1.1)
where g : N > R is some monotonically increasing function. For example, in the
case of binary classification problems, we can take g(d) to be the VC-dimension
of the class Hy multiplied by a universal constant (the one appearing in the
fundamental theorem of learning; see Theorem 6.8). For the classes L(B,d) used
by AdaBoost, the function g will simply grow with d.

Recall that the SRM rule follows a “bound minimization” approach, where in
our case the bound is as follows: With probability of at least 1 — 6, for every
dé€Nandhe Hg,

Lp(h) < Leth) [eet F2log(@ Ho) ayy

m

This bound, which follows directly from Theorem 7.4, shows that for every d and
every h € Ha, the true risk is bounded by two terms — the empirical risk, Ls(h),

146

11.2

11.2.1

Model Selection and Validation

and a complexity term that depends on d. The SRM rule will search for d and
h € Ha that minimize the right-hand side of Equation (11.2).

Getting back to the example of polynomial regression described earlier, even
though the empirical risk of the 10th degree polynomial is smaller than that of
the 3rd degree polynomial, we would still prefer the 3rd degree polynomial since
its complexity (as reflected by the value of the function g(d)) is much smaller.

While the SRM approach can be useful in some situations, in many practical
cases the upper bound given in Equation (11.2) is pessimistic. In the next section
we present a more practical approach.

Validation

We would often like to get a better estimation of the true risk of the output pre-
dictor of a learning algorithm. So far we have derived bounds on the estimation
error of a hypothesis class, which tell us that for all hypotheses in the class, the
true risk is not very far from the empirical risk. However, these bounds might be
loose and pessimistic, as they hold for all hypotheses and all possible data dis-
tributions. A more accurate estimation of the true risk can be obtained by using
some of the training data as a validation set, over which one can evalutate the
success of the algorithm’s output predictor. This procedure is called validation.

Naturally, a better estimation of the true risk is useful for model selection, as
we will describe in Section 11.2.2.

Hold Out Set

The simplest way to estimate the true error of a predictor h is by sampling an ad-
ditional set of examples, independent of the training set, and using the empirical

error on this validation set as our estimator. Formally, let V = (x1, y1),---,(Xmys Ym.)

be a set of fresh m, examples that are sampled according to D (independently of
the m examples of the training set S'). Using Hoeffding’s inequality ( Lemma 4.5)
we have the following:

THEOREM 11.1 Let h be some predictor and assume that the loss function is in
[0,1]. Then, for every 6 € (0,1), with probability of at least 1—6 over the choice
of a validation set V of size m, we have

[Lv(h) — Eo(h)| <4 BCL),

The bound in Theorem 11.1 does not depend on the algorithm or the training
set used to construct hf and is tighter than the usual bounds that we have seen so
far. The reason for the tightness of this bound is that it is in terms of an estimate
on a fresh validation set that is independent of the way h was generated. To
illustrate this point, suppose that h was obtained by applying an ERM predictor

11.2.2

11.2 Validation 147

with respect to a hypothesis class of VC-dimension d, over a training set of m
examples. Then, from the fundamental theorem of learning (Theorem 6.8) we

obtain the bound
d+ log(1/6
Lp(h) < Ls(h) +4/C a ttestt/0),

where C is the constant appearing in Theorem 6.8. In contrast, from Theo-
rem 11.1 we obtain the bound

Lp(h) < Ly(h) +

log(2/5)
2

v

Therefore, taking m, to be order of m, we obtain an estimate that is more
accurate by a factor that depends on the VC-dimension. On the other hand, the
price we pay for using such an estimate is that it requires an additional sample
on top of the sample used for training the learner.

Sampling a training set and then sampling an independent validation set is
equivalent to randomly partitioning our random set of examples into two parts,
using one part for training and the other one for validation. For this reason, the
validation set is often referred to as a hold out set.

Validation for Model Selection

Validation can be naturally used for model selection as follows. We first train
different algorithms (or the same algorithm with different parameters) on the
given training set. Let H = {h1,...,h,} be the set of all output predictors of the
different algorithms. For example, in the case of training polynomial regressors,
we would have each h, be the output of polynomial regression of degree r. Now,
to choose a single predictor from H we sample a fresh validation set and choose
the predictor that minimizes the error over the validation set. In other words,
we apply ERM over the validation set.
This process is very similar to learning a finite hypothesis class. The only
difference is that H is not fixed ahead of time but rather depends on the train-
ing set. However, since the validation set is independent of the training set we

get that it is also independent of H and therefore the same technique we used
to derive bounds for finite hypothesis classes holds here as well. In particular,

combining Theorem 11.1 with the union bound we obtain:

THEOREM 11.2 Let H = {hi,...,hr} be an arbitrary set of predictors and
assume that the loss function is in [0,1]. Assume that a validation set V of size
My is sampled independent of H. Then, with probability of at least 1—6 over the
choice of V we have

VhEH, |Lo(h) —Ly(h)| < test2\7A/0)

148 Model Selection and Validation

This theorem tells us that the error on the validation set approximates the
true error as long as H is not too large. However, if we try too many methods
(resulting in |H| that is large relative to the size of the validation set) then we’re

in danger of overfitting.

To illustrate how validation is useful for model selection, consider again the
example of fitting a one dimensional polynomial as described in the beginning
of this chapter. In the following we depict the same training set, with ERM
polynomials of degree 2, 3, and 10, but this time we also depict an additional

validation set (marked as red, unfilled circles). The polynomial of degree 10 has
minimal training error, yet the polynomial of degree 3 has the minimal validation
error, and hence it will be chosen as the best model.

>

11.2.3 The Model-Selection Curve

The model selection curve shows the training error and validation error as a func-
tion of the complexity of the model considered. For example, for the polynomial
fitting problem mentioned previously, the curve will look like:

11.2.4

11.2 Validation 149

0.4 —— train
—e— validation
0.3 - |
a
oS  0.2- 4
S
0.1 + |
0 = 4
L L L L L
2 4 6 8 10
d

As can be shown, the training error is monotonically decreasing as we increase

he polynomial degree (which is the comp.
he other hand, the validation error first

correct regime of our parameter space. Of

exity of the model in our case). On
lecreases but then starts to increase,

which indicates that we are starting to suffer from overfitting.
Plotting such curves can help us understand whether we are searching the

en, there may be more than a single

parameter to tune, and the possible number of values each parameter can take
might be quite large. For example, in Chapter 13 we describe the concept of
regularization, in which the parameter of the learning algorithm is a real number.

In such cases, we start with a rough grid o:

values for the parameter(s) and plot

he corresponding model-selection curve. On the basis of the curve we will zoom
in to the correct regime and employ a finer grid to search over. It is important to

verify that we are in the relevant regime. For example, in the polynomial fitting

problem described, if we start searching degrees from the set of values {1, 10, 20}

and do not employ a finer grid based on the resulting curve, we will end up with

a rather poor model.

k-Fold Cross Validation

The validation procedure described so far assumes that data is plentiful and that

we have the ability to sample a fresh validation set. But in some applications,
data is scarce and we do not want to “waste” data on validation. The k-fold

cross validation technique is designed to give an accurate estimate of the true

error without wasting too much data.

In k-fold cross validation the original trai

ining set is partitioned into k subsets

(folds) of size m/k (for simplicity, assume that m/k is an integer). For each fold,
the algorithm is trained on the union of the other folds and then the error of its
output is estimated using the fold. Finally, the average of all these errors is the

150

11.2.5

Model Selection and Validation

estimate of the true error. The special case k = m, where m is the number of
examples, is called leave-one-out (LOO).

k-Fold cross validation is often used for model selection (or parameter tuning),
and once the best parameter is chosen, the algorithm is retrained using this
parameter on the entire training set. A pseudocode of k-fold cross validation
for model selection is given in the following. The procedure receives as input a
training set, S, a set of possible parameter values, O, an integer, k, representing
the number of folds, and a learning algorithm, A, which receives as input a
training set as well as a parameter 6 € O. It outputs the best parameter as well
as the hypothesis trained by this parameter on the entire training set.

k-Fold Cross Validation for Model Selection

input:
training set S = (x1,41),---;(Km,Ym)
set of parameter values O
learning algorithm A
integer k
partition S into $1, S9,...,Sz
foreach 6 € 0
fori=1...k
hig = A(S \ Si; 0)
error(9) = ¢ ye Ls, (hi,o)

output
6* = argmin, [error(6)|
ho» = A(S;6*)

The cross validation method often works very well in practice. However, it
might sometime fail, as the artificial example given in Exercise 1 shows. Rig-
orously understanding the exact behavior of cross validation is still an open
problem. Rogers and Wagner (Rogers & Wagner 1978) have shown that for k
local rules (e.g., k Nearest Neighbor; see Chapter 19) the cross validation proce-
dure gives a very good estimate of the true error. Other papers show that cross
validation works for stable algorithms (we will study stability and its relation to
learnability in Chapter 13).

Train-Validation-Test Split

In most practical applications, we split the available examples into three sets.
The first set is used for training our algorithm and the second is used as a
validation set for model selection. After we select the best model, we test the
performance of the output predictor on the third set, which is often called the
“test set.” The number obtained is used as an estimator of the true error of the
learned predictor.

11.3

11.3 What to Do If Learning Fails 151

What to Do If Learning Fails

Consider the following scenario: You were given a learning task and have ap-
proached it with a choice of a hypothesis class, a learning algorithm, and param-
eters. You used a validation set to tune the parameters and tested the learned
predictor on a test set. The test results, unfortunately, turn out to be unsatis-
factory. What went wrong then, and what should you do next?

There are many elements that can be “fixed.” The main approaches are listed
in the following:

e Get a larger sample
e Change the hypothesis class by:
— Enlarging it
— Reducing it
— Completely changing it
— Changing the parameters you consider
e Change the feature representation of the data
e Change the optimization algorithm used to apply your learning rule

In order to find the best remedy, it is essential first to understand the cause
of the bad performance. Recall that in Chapter 5 we decomposed the true er-
ror of the learned predictor into approximation error and estimation error. The
approximation error is defined to be Lp(h*) for some h* € argmin,.z Lp(h),
while the estimation error is defined to be Lp(hs) — Lp(h*), where hg is the
learned predictor (which is based on the training set S).

The approximation error of the class does not depend on the sample size or
on the algorithm being used. It only depends on the distribution D and on the
hypothesis class H. Therefore, if the approximation error is large, it will not help
us to enlarge the training set size, and it also does not make sense to reduce the
hypothesis class. What can be beneficial in this case is to enlarge the hypothesis
class or completely change it (if we have some alternative prior knowledge in

the form of a different hypothesis class). We can also consider applying the
same hypothesis class but on a different feature representation of the data (see
Chapter 25).

The estimation error of the class does depend on the sample size. Therefore, if
we have a large estimation error we can make an effort to obtain more training
examples. We can also consider reducing the hypothesis class. However, it doesn’t
make sense to enlarge the hypothesis class in that case.

Error Decomposition Using Validation
We see that understanding whether our problem is due to approximation error

or estimation error is very useful for finding the best remedy. In the previous
section we saw how to estimate Lp(hg) using the empirical risk on a validation
set. However, it is more difficult to estimate the approximation error of the class.

152

Model Selection and Validation

Instead, we give a different error decomposition, one that can be estimated from
the train and validation sets.

Lp(hs) = (Lp(hs) — Lv(hs)) + (Lv (hs) — Ls(hs)) + Ls(hs).

The first term, (Lp(hs) — Ly(hg)), can be bounded quite tightly using Theo-
rem 11.1. Intuitively, when the second term, (Ly (hs) — Ls(hg)), is large we say
that our algorithm suffers from “overfitting” while when the empirical risk term,
Lg(hg), is large we say that our algorithm suffers from “underfitting.” Note that
these two terms are not necessarily good estimates of the estimation and ap-
proximation errors. To illustrate this, consider the case in which H is a class of
VC-dimension d, and D is a distribution such that the approximation error of
with respect to D is 1/4. As long as the size of our training set is smaller than
d we will have Ls(hs) = 0 for every ERM hypothesis. Therefore, the training
risk, Lg (hg), and the approximation error, Lp(h*), can be significantly different.
Nevertheless, as we show later, the values of Ls(hg) and (Ly (hg) — Ls(hg)) still
provide us useful information.

Consider first the case in which Lg(hg) is large. We can write
Lg(hg) = (Ls(hs) — Ls(h*)) + (Ls(h*) — Lp(h*)) + Lp(h*).

When hg is an ERM hypothesis we have that Ls(hs)—Lg(h*) < 0. In addition,
since h* does not depend on S, the term (Lg(h*)—Lp(h*)) can be bounded quite
tightly (as in Theorem 11.1). The last term is the approximation error. It follows
that if Ls(hg) is large then so is the approximation error, and the remedy to the
failure of our algorithm should be tailored accordingly (as discussed previously).

Remark 11.1 It is possible that the approximation error of our class is small,
yet the value of Lg(hg) is large. For example, maybe we had a bug in our ERM
implementation, and the algorithm returns a hypothesis hg that is not an ERM.

It may also be the case that finding an ERM hypothesis is computationally hard,

and our algorithm applies some heuristic trying to find an approximate ERM. In

some cases, it is hard to know how good hs is relative to an ERM hypothesis. But,
sometimes it is possible at least to know whether there are better hypotheses.
For example, in the next chapter we will study convex learning problems in

which there are optimality conditions that can be checked to verify whether
our optimization algorithm converged to an ERM solution. In other cases, the
solution may depend on randomness in initializing the algorithm, so we can try
different randomly selected initial points to see whether better solutions pop out.

Next consider the case in which Lg(hg) is small. As we argued before, this

does not necessarily imply that the approximation error is small. Indeed, consider
two scenarios, in both of which we are trying to learn a hypothesis class of

VC-dimension d using the ERM learning rule. In the first scenario, we have a

training set of m < d examples and the approximation error of the class is high.
In the second scenario, we have a training set of m > 2d examples and the

11.3 What to Do If Learning Fails 153

error error

validation error vay;
° © 8 0 6 oo fo ation
erp,
or

°° ° °
°

°
°

© 0 og

. train error
train error

Figure 11.1 Examples of learning curves. Left: This learning curve corresponds to the
scenario in which the number of examples is always smaller than the VC dimension of
the class. Right: This learning curve corresponds to the scenario in which the
approximation error is zero and the number of examples is larger than the VC
dimension of the class.

approximation error of the class is zero. In both cases Lg(hg) = 0. How can we
distinguish between the two cases?

Learning Curves
One possible way to distinguish between the two cz

s is by plotting learning

curves. To produce a learning curve we train the algorithm on prefixes of the
data of increasing sizes. For example, we can first train the algorithm on the
first 10% of the examples, then on 20% of them, and so on. For each prefix we
calculate the training error (on the prefix the algorithm is being trained on)
and the validation error (on a predefined validation set). Such learning curves
can help us distinguish between the two aforementioned scenarios. In the firs
scenario we expect the validation error to be approximately 1/2 for all prefixes,
as we didn’t really learn anything. In the second scenario the validation error
will start as a constant but then should start decreasing (it must start decreasing
once the training set size is larger than the VC-dimension). An illustration o
the two cases is given in Figure 11.1.

In general, as long as the approximation error is greater than zero we expec
the training error to grow with the sample size, as a larger amount of data points
makes it harder to provide an explanation for all of them. On the other hand,
the validation error tends to decrease with the increase in sample size. If the

VC-dimension is finite, when the sample size goes to infinity, the validation an
train errors converge to the approximation error. Therefore, by extrapolating
the training and validation curves we can try to guess the value of the approx-
imation error, or at least to get a rough estimate on an interval in which the
approximation error resides.

Getting back to the problem of finding the best remedy for the failure of
our algorithm, if we observe that Ls(hg) is small while the validation error is
large, then in any case we know that the size of our training set is not sufficient
for learning the class H. We can then plot a learning curve. If we see that the

154

11.4

11.5

Model Selection and_ Validation

validation error is starting to decrease then the best solution is to increase the
number of examples (if we can afford to enlarge the data). Another reasonable
solution is to decrease the complexity of the hypothesis class. On the other hand,
if we see that the validation error is kept around 1/2 then we have no evidence
that the approximation error of H is good. It may be the case that increasing
the training set size will not help us at all. Obtaining more data can still help
us, as at some point we can see whether the validation error starts to decrease

or whether the training error starts to increase. But, if more data is expensive,
it may be better first to try to reduce the complexity of the hypothesis class.

To summarize the discussion, the following steps should be applied:

earning involves parameter tuning, plot the model-selection curve to make
ure that you tuned the parameters appropriately (see Section 11.2.3).

f the training error is excessively large consider enlarging the hypothesis class,
completely change it, or change the feature representation of the data.

f the training error is small, plot learning curves and try to deduce from them
whether the problem is estimation error or approximation error.

De

How

. If the approximation error seems to be small enough, try to obtain more data.

If this is not possible, consider reducing the complexity of the hypothesis class.

. If the approximation error seems to be large as well, try to change the hy-

pothesis class or the feature representation of the data completely.

Summary

Model selection is the task of selecting an appropriate model for the learning
task based on the data itself. We have shown how this can be done using the
SRM learning paradigm or using the more practical approach of validation. If
our learning algorithm fails, a decomposition of the algorithm’s error should be
performed using learning curves, so as to find the best remedy.

Exercises

1.

Failure of k-fold cross validation Consider a case in that the label is
chosen at random according to P{y = 1] = Ply = 0] = 1/2. Consider a
learning algorithm that outputs the constant predictor h(x) = 1 if the parity
of the labels on the training set is 1 and otherwise the algorithm outputs the
constant predictor h(x) = 0. Prove that the difference between the leave-one-
out estimate and the true error in such a case is always 1/2.

. Let Hi,...,H, be k hypothesis classes. Suppose you are given m i.i.d. training

examples and you would like to learn the class H = US_,H;. Consider two
alternative approaches:

e Learn H on the m examples using the ERM rule

11.5 Exercises 155

e Divide the m examples into a training set of size (1—a)m and a validation
set of size am, for some a € (0,1). Then, apply the approach of model
selection using validation. That is, first train each class H; on the (1 —
a)m training examples using the ERM rule with respect to H;, and let

hy,..., hy be the resulting hypotheses. Second, apply the ERM rule with
respect to the finite class fhy, beng he} on the am validation examples.

Describe scenarios in which the first method is better than the second and

vice versa.

12

12.1

12.1.1

Convex Learning Problems

In this chapter we introduce convex learning problems. Convex learning comprises
an important family of learning problems, mainly because most of what we can
learn efficiently falls into it. We have already encountered linear regression with
the squared loss and logistic regression, which are convex problems, and indeed
they can be learned efficiently. We have also seen nonconvex problems, such as
halfspaces with the 0-1 loss, which is known to be computationally hard to learn
in the unrealizable case.

In general, a convex learning problem is a problem whose hypothesis class is a
convex set, and whose loss function is a convex function for each example. We be-
gin the chapter with some required definitions of convexity. Besides convexity, we

will define Lipschitzness and smoothness, which are additional properties of the

oss function that facilitate successful learning. We next turn to defining convex

earning problems and demonstrate the necessity for further constraints such as

Boundedness and Lipschitzness or Smoothness. We define these more restricted

amilies of learning problems and claim that Convex-Smooth/Lipschitz-Bounded

problems are learnable. These claims will be proven in the next two chapters, in

which we will present two learning paradigms that successfully learn all problems

hat are either convex-Lipschitz-bounded or convex-smooth-bounded.
Finally, in Section 12.3, we show how one can handle some nonconvex problems

by minimizing “surrogate” loss functions that are convex (instead of the original
nonconvex loss function). Surrogate convex loss functions give rise to efficient
solutions but might increase the risk of the learned predictor.

Convexity, Lipschitzness, and Smoothness

Convexity

DEFINITION 12.1 (Convex Set) A set C in a vector space is convex if for any
two vectors u, v in C, the line segment between u and v is contained in C. That
is, for any a € [0,1] we have that au+(1—a)v EC.

Examples of convex and nonconvex sets in R? are given in the following. For
the nonconvex sets, we depict two points in the set such that the line between
the two points is not contained in the set.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

12.1 Convexity, Lipschitzness, and Smoothness 157

non-convex convex

oY OF

Given a € [0,1], the combination, au + (1 — a)v of the points u, v is called a

convex combination.

DEFINITION 12.2 (Convex Function) Let C be a convex set. A function f :
C > R is convex if for every u,v € C and a € (0, 1],

f(eu+(-a)v) < af(u) + -a)f(y) .
In words, f is convex if for any u,v, the graph of f between u and v lies below

the line segment joining f(u) and f(v). An illustration of a convex function,
f :R—-R, is depicted in the following.

af(u) + (1 - a)f(v)

f(au + (1 — a)v)

i=}
as

° °
au +(1—a)v

The epigraph of a function f is the set
epigraph(f) = {(x, 8): f(x) < GB}. (12.1)
It is easy to verify that a function f is convex if and only if its epigraph is a

convex set. An illustration of a nonconvex function f : R > R, along with its

epigraph, is given in the following.

158

Convex Learning Problems

f(z)

An important property of convex functions is that every local minimum of the

function is also a global minimum. Formally, let B(u,r) = {v: ||v — ul] <r} be
a ball of radius r centered around u. We say that f(u) is a local minimum of f
at u if there exists some r > 0 such that for all v € B(u,r) we have f(v) > f(u).
It follows that for any v (not necessarily in B), there is a small enough a > 0
such that u+a(v —u) € B(u,r) and therefore

f(u) < f(ut+a(v—u)). (12.2)
If f is convex, we also have that
f(a av —u)) = flav +(1—a)u) <(1—a)f(u) +af(v). (12.3)

Combining these two equations and rearranging terms, we conclude that f(u) <
f(v). Since this holds for every v, it follows that f(u) is also a global minimum
of f.

Another important property of convex functions is that for every w we can
construct a tangent to f at w that lies below f everywhere. If f is differentiable,
this tangent is the linear function I(u) = f(w) + (Vf(w),u—w), where V f(w)
is the gradient of f at w, namely, the vector of partial derivatives of f, Vf(w) =
(= Of wy)

Fu ). That is, for convex differentiable functions,
1 Wd

Vu, f(u) > f(w)+ (Vf(w),u—w). (12.4)

In Chapter 14 we will generalize this inequality to nondifferentiable functions.
An illustration of Equation (12.4) is given in the following.

12.1 Convexity, Lipschitzness, and Smoothness 159

If f is a scalar differentiable function, there is an easy way to check if it is
convex.

LEMMA 12.3 Let f : R > R be a scalar twice differential function, and let
f', f" be its first and second derivatives, respectively. Then, the following are
equivalent:

1. f is conver

2. f' is monotonically nondecreasing
3. f” is nonnegative

Example 12.1

e The scalar function f(x) = 2?
and f"(x) =2>0.

e The scalar function f(x) = log(1+exp(x)) is convex. To see this, observe that.

is convex. To see this, note that f’(x) = 2x

f'(«) = =e = =pCait This is a monotonically increasing function

since the exponent function is a monotonically increasing function.

The following claim shows that the composition of a convex scalar function
with a linear function yields a convex vector-valued function.

CLAIM 12.4 Assume that f : R¢ + R can be written as f(w) = g((w,x) + y),
for some x € R¢, y € R, andg: R +R. Then, convexity of g implies the
convexity of f.

Proof Let w1,w2 € R¢ and a € [0,1]. We have

f(awi + (1 — @)w2) = g((awi + (1 — a)we,x) + y)

= g(a(w1,x) + (1 — a) (we, x) +)
g(a((wi, x) + y) + (1 — @)((wa,x) + y))

ag((wi,x) +y) + (1—a)g((we,x) +9),

| 4

where the last inequality follows from the convexity of g.

Example 12.2

160

12.1.2

Convex Learning Problems

e Given some x € R¢

and y € R, let f : R¢ > R be defined as f(w) =

((w,x) — y)?. Then, f is a composition of the function g(a) = a? onto a

linear function, and hence f is a convex function.
e Given some x € R4 and y € {+1}, let f : R¢ + R be defined as f(w) =

log(1 + exp(—y(w,
log(1 + exp(a)) ont

Finally, the following
convex and that a weigh
is also convex.

CLAIM 12.5 Fori =
following functions from

© g(x) = maxyetr) fi(x)
© g(x) = Din wifila),

x))). Then, f is a composition of the function g(a) =
o a linear function, and hence f is a convex function.

emma shows that the maximum of convex functions is
ed sum of convex functions, with nonnegative weights,

y.o57, let fi : R¢  R be a convex function. The
R¢ to R are also convex.

where for alli, w; > 0.

Proof The first claim follows by

g(au + (1

For the second claim

g(au + (1 =

a)v) max fi(ou + (1—a)v)
< max (af.(u) + (1a) f(0)
< omax fi(u) + (1 - a) max fi(v)

=ag(u) + (1—a)g(v).

a)v) = » wifi(au + (1 — a)v)
< » wi; [afi(u) + (1 — a) fi(v)]
= ay wifi(u) +(1— a) Ss wifi(v)

a

= ag(u) + (1—a)g(v).

Example 12.3 The function g(x) = |x| is convex. To see this, note that g(x) =

max{x,—2} and that both the function f(x) = # and f2(x) = —x are convex.

Lipschitzness

The definition of Lipschitzness below is with respect to the Euclidean norm over

R¢. However, it is possible to define Lipschitzness with respect to any norm.

DEFINITION 12.6 (Lips

chitzness) Let C Cc R¢. A function f : R¢ > R* is

p-Lipschitz over C' if for every w1,w2 € C we have that || f(wi) — f(we)|| <

p||wi — wall.

12.1 Convexity, Lipschitzness, and Smoothness 161

Intuitively, a Lipschitz function cannot change too fast. Note that if f: RR
is differentiable, then by the mean value theorem we have
f(w1) — f(w2) = f(u)(wr = we) ,

where u is some point between w; and wo. It follows that if the derivative of f
is everywhere bounded (in absolute value) by p, then the function is p-Lipschitz.

Example 12.4

e The function f(z) = |x| is 1-Lipschitz over R. This follows from the triangle
inequality: For every 71, x2,

|x1| — |v] = lar — x2 + x9| — |e] < |a1 — 2| + [x2 — |r| = [2x1 — x9].

Since this holds for both x1, x2 and x2,21, we obtain that ||x1| — |xl| <

Jay — ao].
e The function f(x) = log(1+exp(z)) is 1-Lipschitz over R. To see this, observe

that

exp(z) 1
"| <1,
1+ exp(z) exp(—a) +1

e The function f(x) = 2? is not p-Lipschitz over R for any p. To see this, take
x, =O and z2 =1+~, then

f (x2) — f(a1) = (1+ p)? > p+) = pire — 2].

However, this function is p-Lipschitz over the set C = {a : |2| < p/2}.
Indeed, for any 21,72 € C we have

|ej —25| = |r + wal jer — 2| < 2(p/2) |e — wa] = pla — 29].

e The linear function f : R¢ + R defined by f(w) = (v,w) +b where v € R¢
is ||v||-Lipschitz. Indeed, using Cauchy-Schwartz inequality,
|f(w1) — Fwa)| = [(v, wi = wa)| < ||¥|] [wa — wll.
The following claim shows that composition of Lipschitz functions preserves

Lipschitzness.

CLAIM 12.7. Let f(x) = gi (g2(x)), where gi is pi-Lipschitz and go is p2-
Lipschitz. Then, f is (p1p2)-Lipschitz. In particular, if gz is the linear function,
g2(x) = (v,x) +b, for some v € R4,bER, then f is (py ||v||)-Lipschitz.

Proof
|f(w1) — f(wa2)| = |g1(g2(w1)) — 91(92(we))|

< pillg2(wi) — g2(we))h

< pi p2 ||wi — wo).


162 Convex Learning Problems

12.1.3 Smoothness

The definition of a smooth function relies on the notion of gradient. Recall that
the gradient of a differentiable function f : R¢ > R at w, denoted Vf (w), is the
af w) af co).

vector of partial derivatives of f, namely, Vf(w) = ( To? Dang

DEFINITION 12.8 (Smoothness) A differentiable function f : R¢ > R is 6-
smooth if its gradient is $-Lipschitz; namely, for all v,w we have ||Vf(v) —

Vf (w)|| < Bllv — wI)-
It is possible to show that smoothness implies that for all v,w we have

lv) < Sw) + (Ws (w),v —w) +5

Recall that convexity of f implies that f(v) > f(w)+(Vf(w), v—w). Therefore,
when a function is both convex and smooth, we have both upper and lower

|v — wl? . (12.5)

bounds on the difference between the function and its first order approximation.
Setting v = w — 3Vi(w) in the right-hand side of Equation (12.5) and rear-
ranging terms, we obtain
1

salVF) I < Fw) ~ F().

If we further assume that f(v) > 0 for all v we conclude that smoothness implies
the following:

IV Sow)? < 26 FCW) . (12.6)
A function that satisfies this property is also called a self-bounded function.

Example 12.5

e The function f(x) = x? is 2-smooth. This follows directly from the fact that
f'(x) = 2x. Note that for this particular function Equation (12.5) and
Equation (12.6) hold with equality.

e The function f(x) = log(1 + exp(x)) is (1/4)-smooth. Indeed, since f’(a) =

1 avi P
Trexptcay We have that

exp(—2) 1
(1+ exp(—a))? (1+ exp(—2))(1 + exp(x))

\f"()|

< 1/4.
Hence, f’ is (1/4)-Lipschitz. Since this function is nonnegative, Equa-
tion (12.6) holds as well.

The following claim shows that a composition of a smooth scalar function over
a linear function preserves smoothness.

CLAIM 12.9 Let f(w) = g((w,x)+b), where g: R > R is a 8-smooth function,
x €R¢, andbeR. Then, f is (8 ||x||?)-smooth.

12.2

12.2 Convex Learning Problems 163

Proof By the chain rule we have that V f(w) = g/((w, x) +)x, where g’ is the
derivative of g. Using the smoothness of g and the Cauchy-Schwartz inequality
we therefore obtain
f(v) = gv, x) +8)
B

< g({w, x) +b) + 9'((w, x) + b)(v — wx) + Zw —w,x))
B
2
?.

2

< g((w, x) +) + 9!((w, x) +b)(v — w, x) + 5 (lv — wl lx)”

Bll?

= f(w) + (VF 0w),v —w) +

lv — w|

Example 12.6

e For any x € R4 andy € R, let f(w) = ((w,x) — y)?. Then, f is (2||x||?)-
smooth.

e For any x € R4 and y € {+1}, let f(w) = log(1 + exp(—y(w,x))). Then, f is
(||x||?/4)-smooth.

Convex Learning Problems

Recall that in our general definition of learning (Definition 3.4 in Chapter 3), we
have a hypothesis class H, a set of examples Z, and a loss function ¢: Hx Z >
R,. So far in the book we have mainly thought of Z as being the product of an
instance space and a target space, Z = ¥ x Y, and H being a set of functions from
&X to Y. However, H can be an arbitrary set. Indeed, throughout this chapter,
we consider hypothesis classes 1 that are subsets of the Euclidean space R¢.

That is, every hypothesis is some real-valued vector. We shall, therefore, denote

a hypothesis in H by w. Now we can finally define convex learning problems:

DEFINITION 12.10 (Convex Learning Problem) A learning problem, (H, Z, £),
is called convex if the hypothesis class H is a convex set and for all z € Z, the
loss function, ¢(-,z), is a convex function (where, for any z, ¢(-,z) denotes the
function f : H — R defined by f(w) = ¢(w, z)).

Example 12.7 (Linear Regression with the Squared Loss) Recall that linear
regression is a tool for modeling the relationship between some “explanatory”
variables and some real valued outcome (see Chapter 9). The domain set ¥
is a subset of R¢, for some d, and the label set Y is the set of real numbers.

We would like to learn a linear function h : R¢ > R that best approximates
the relationship between our variables. In Chapter 9 we defined the hypothesis
class as the set of homogenous linear functions, H = {x +> (w,x) : w € R*},
and used the squared loss function, f(h, (x, y)) = (h(x) — y)?. However, we can
equivalently model the learning problem as a convex learning problem as follows.

164

12.2.1

Convex Learning Problems

Each linear function is parameterized by a vector w € R¢. Hence, we can define
H to be the set of all such parameters, namely, H = R¢. The set of examples is
Z=XxyY=RtxR=R"!, and the loss function is ¢(w, (x, y)) = ((w,x)—y)?.
Clearly, the set H is a convex set. The loss function is also convex with respect
to its first argument (see Example 12.2).

LEMMA 12.11 If is a convex loss function and the class H is convex, then the
ERM, problem, of minimizing the empirical loss over H, is a convex optimiza-
tion problem (that is, a problem of minimizing a convex function over a conver
set).

Proof Recall that the ERM problem is defined by

ERMy,(S) = argmin Ls(w).

weH

Since, for a sample S = 21,...,2m, for every w, Ls(w) = Po per E(w, 2);
Claim 12.5 implies that Lg(w) is a convex function. Therefore, the ERM rule

is a problem of minimizing a convex function subject to the constraint that the

solution should be in a convex set.

Under mild conditions, such problems can be solved efficiently using generic
optimization algorithms. In particular, in Chapter 14 we will present a very
simple algorithm for minimizing convex functions.

Learnability of Convex Learning Problems

We have argued that for many cases, implementing the ERM rule for convex
earning problems can be done efficiently. But is convexity a sufficient condition
‘or the learnability of a problem?

To make the quesion more specific: In VC theory, we saw that halfspaces in
d-dimension are learnable (perhaps inefficiently). We also argued in Chapter 9
using the “discretization trick” that if the problem is of d parameters, it is
earnable with a sample complexity being a function of d. That is, for a constant
d, the problem should be learnable. So, maybe all convex learning problems over
R¢, are learnable?

Example 12.8 later shows that the answer is negative, even when d is low. Not
all convex learning problems over R@ are learnable. There is no contradiction
o VC theory since VC theory only deals with binary classification while here
we consider a wide family of problems. There is also no contradiction to the
“discretization trick” as there we assumed that the loss function is bounded and
also assumed that a representation of each parameter using a finite number of
bits suffices. As we will show later, under some additional restricting conditions

hat hold in many practical scenarios, convex problems are learnable.

Example 12.8 (Nonlearnability of Linear Regression Even Ifd = 1) Let H =R,
and the loss be the squared loss: ((w, (x, y)) = (wa — y)? (we're referring to the


12.2 Convex Learning Problems 165

homogenous case). Let A be any deterministic algorithm.! Assume, by way of
contradiction, that A is a successful PAC learner for this problem. That is, there
exists a function m/(-,-), such that for every distribution D and for every e,6 if
A receives a training set of size m > m/(e,6), it should output, with probability
of at least 1 — 6, a hypothesis w = A(S), such that Lp(w) — min,, Lp(w) <.

Choose € = 1/100,6 = 1/2, let m > m(e,6), and set pp = tos 000/99) | We will
define two distributions, and will show that A is likely to fail on at least one
of them. The first distribution, D,, is supported on two examples, z, = (1,0)
and z2 = (#1, —1), where the probability mass of the first example is jz while the
probability mass of the second example is 1 — jz. The second distribution, Do, is

supported entirely on z2.

Observe that for both distributions, the probability that all examples of the
training set will be of the second type is at least 99%. This is trivially true for
D2, whereas for D,, the probability of this event is

(1—p)™ > e-2#™ = 0.99.

Since we assume that A is a deterministic algorithm, upon receiving a training
set of m examples, each of which is (4, —1), the algorithm will output some w.
Now, if w < —1/(2u), we will set the distribution to be D,. Hence,

Lp, (@) > p(w)? > 1/(4p).

However,
min Lp, (w) < Lp, (0) = (1—p).
w
It follows that
1
Lp, (w) — min Lp, (w) > — -(1-p) >e.
w Aw
Therefore, such algorithm A fails on D,. On the other hand, if # > —1/(2)
then we’ll set the distribution to be Dz. Then we have that Lp, (w) > 1/4 whi
min, Lp,(w) = 0, so A fails on D2. In summary, we have shown that for every
A there exists a distribution on which A fails, which implies that the problem is
not PAC learnable.

A possible solution to this problem is to add another constraint on the hypoth-
esis class. In addition to the convexity requirement, we require that H will be

io)

bounded; namely, we assume that for some predefined scalar B, every hypothesis
w € H satisfies ||w|| < B.

Boundedness and convexity alone are still not sufficient for ensuring that the
problem is learnable, as the following example demonstrates.

Example 12.9 As in Example 12.8, consider a regression problem with the
squared loss. However, this time let H = {w : |w| < 1} C R be a bounded
1 Namely, given S the output of A is determined. This requirement is for the sake of

simplicity. A slightly more involved argument will show that nondeterministic algorithms
will also fail to learn the problem.

166

12.2.2

Convex Learning Problems

hypothesis class. It is easy to verify that H is convex. The argument will be
the same as in Example 12.8, except that now the two distributions, D,, D2 will
be supported on z = (1/y,0) and z2 = (1,—1). If the algorithm A returns
w < —1/2 upon receiving m examples of the second type, then we will set the
distribution to be D; and have that

Lp, (to) — min Lp, (w) > u(td/u)” — Lp, (0) > 1/(4n) — (1 -p) >.
Similarly, if @ > —1/2 we will set the distribution to be D2 and have that
Lp, (wv) — min Lp, (w) > (—1/2+1)? -0>6.
w

This example shows that we need additional assumptions on the learning
problem, and this time the solution is in Lipschitzness or smoothness of the
loss function. This motivates a definition of two families of learning problems,
convex-Lipschitz-bounded and convex-smooth-bounded, which are defined later.

Convex-Lipschitz/Smooth-Bounded Learning Problems

DEFINITION 12.12 (Convex-Lipschitz-Bounded Learning Problem) A learning
problem, (H, Z, £), is called Convex-Lipschitz-Bounded, with parameters p, B if
the following holds:

e The hypothesis class H is a convex set and for all w € H we have ||w|| < B.

e For all z € Z, the loss function, ¢(-, z), is a convex and p-Lipschitz function.

Example 12.10 Let X = {x € R@: ||x|| < p} and Y=R. Let H = {we R?:
||w|| < B} and let the loss function be ¢(w, (x,y)) = |(w,x) — y|. This corre-
sponds to a regression problem with the absolute-value loss, where we assume
that the instances are in a ball of radius p and we restrict the hypotheses to be
homogenous linear functions defined by a vector w whose norm is bounded by
B. Then, the resulting problem is Convex-Lipschitz-Bounded with parameters
p, B.

DEFINITION 12.13 (Convex-Smooth-Bounded Learning Problem) A learning
problem, (H, Z,¢), is called Convex-Smooth-Bounded, with parameters 6, B if
the following holds:

e The hypothesis class H is a convex set and for all w € H we have ||w|| < B.
e For all z € Z, the loss function, ¢(-, z), is a convex, nonnegative, and 8-smooth
function.

Note that we also required that the loss function is nonnegative. This is needed
to ensure that the loss function is self-bounded, as described in the previous
section.

12.3

12.3 Surrogate Loss Functions 167

Example 12.11 Let ¥ = {x € R¢: ||x|| < 6/2} and Y=R. Let H = {we
R¢ : ||w|| < B} and let the loss function be &(w, (x, y)) = ((w,x) — y)?. This
corresponds to a regression problem with the squared loss, where we assume that
the instances are in a ball of radius 3/2 and we restrict the hypotheses to be
homogenous linear functions defined by a vector w whose norm is bounded by B.
Then, the resulting problem is Convex-Smooth-Bounded with parameters 3, B.

We claim that these two families of learning problems are learnable. That is,
the properties of convexity, boundedness, and Lipschitzness or smoothness of the
loss function are sufficient for learnability. We will prove this claim in the next
chapters by introducing algorithms that learn these problems successfully.

Surrogate Loss Functions

As mentioned, and as we will see in the next chapters, convex problems can
be learned efficiently. However, in many cases, the natural loss function is not
convex and, in particular, implementing the ERM rule is hard.

As an example, consider the problem of learning the hypothesis class of half-
spaces with respect to the 0 — 1 loss. That is,

Ow, (&.Y)) = Uyysien((w.))] = Ly(w,x) <0]:

This loss function is not convex with respect to w and indeed, when trying to
minimize the empirical risk with respect to this loss function we might encounter
local minima (see Exercise 1). Furthermore, as discussed in Chapter 8, solving
the ERM problem with respect to the 0 — 1 loss in the unrealizable case is known
to be NP-hard.

To circumvent the hardness result, one popular approach is to upper bound

the nonconvex loss function by a convex surrogate loss function. As its name
indicates, the requirements from a convex surrogate loss are as follows:

1. It should be convex.

2. It should upper bound the original loss.

For example, in the context of learning halfspaces, we can define the so-called
hinge loss as a convex surrogate for the 0 — 1 loss, as follows:

chinge (w(x, y)) ef max{0, 1 — y(w,x)}.

Clearly, for all w and all (x,y), €°-1(w, (x,y)) < £hi™8¢(w, (x, y)). In addition,
the convexity of the hinge loss follows directly from Claim 12.5. Hence, the hinge
loss satisfies the requirements of a convex surrogate loss function for the zero-one
loss. An illustration of the functions (°-! and ¢*"8° is given in the following.

168 Convex Learning Problems

+.
hinge |%»

por c

*feeeeeee

y(w, x)

Once we have defined the surrogate convex loss, we can learn the problem with

respect to it. The generalization requirement from a hinge loss learner will have
the form

LIs"8°(A(S)) < min LIS" (w) +,

where LB"*°(w) = Ecx,y)~v[E'"®* (w, (x, y))]. Using the surrogate property, we
can lower bound the left-hand side by L%'(A(S)), which yields

Ly (A(S)) <_ min LE" (w) +

We can further rewrite the upper bound as follows:

weH

L*(A(S)) < min Lh w) + (iy Ls"8°(w) — min Us “(w)) +e.
weH weH
That is, the 0—1 error of the learned predictor is upper bounded by three terms:

e Approximation error: This is the term minwey L5*(w), which measures how
well the hypothesis class performs on the distribution. We already elabo-
rated on this error term in Chapter 5.

e Estimation error: This is the error that results from the fact that we only
receive a training set and do not observe the distribution D. We already
elaborated on this error term in Chapter 5.

© Optimization error: This is the term (minyex Lis"®°(w) — minwen LS 1 (w)
that measures the difference between

he approximation error with respect
to

he surrogate loss and the approximation error with respect to the orig-
inal loss. The optimization error is a result of our inability to minimize the
training loss with respect to the original loss. The size of this error depends
on the specific distribution of the data and on the specific surrogate loss
we are using.

12.4 Summary

We introduced two families of learning problems: convex-Lipschitz-bounded and
convex-smooth-bounded. In the next two chapters we will describe two generic

12.5

12.6

12.5 Bibliographic Remarks 169

learning algorithms for these families. We also introduced the notion of convex
surrogate loss function, which enables us also to utilize the convex machinery for
nonconvex problems.

Bibliographic Remarks

There are several excellent books on convex analysis and optimization (Boyd &
Vandenberghe 2004, Borwein & Lewis 2006, Bertsekas 1999, Hiriart-Urruty &
Lemaréchal 1996). Regarding learning problems, the family of convex-Lipschitz-
bounded problems was first studied by Zinkevich (2003) in the context of online
learning and by Shalev-Shwartz, Shamir, Sridharan & Srebro (2009) in the con-
text of PAC learning.

Exercises

1. Construct an example showing that the 0—1 loss function may suffer from
local minima; namely, construct a training sample S' € (X x {+1})” (say, for

X = R?), for which there exist a vector w and some € > 0 such that
1. For any w’ such that ||w — w’|| < € we have Ls(w) < Ls(w’) (where the
loss here is the 0—1 loss). This means that w is a local minimum of Lg.
2. There exists some w* such that Ls(w*) < Ls(w). This means that w is
not a global minimum of Lg.
2. Consider the learning problem of logistic regression: Let H = VY = {x €
R¢ : ||x|| < B}, for some scalar B > 0, let Y = {+1}, and let the loss
function ¢ be defined as ¢(w,(x,y)) = log(1 + exp(—y(w,x))). Show that
he resulting learning problem is both convex-Lipschitz-bounded and convex-

smooth-bounded. Specify the parameters of Lipschitzness and smoothness.
3. Consider the problem of learning halfspaces with the hinge loss. We limit our
domain to the Euclidean ball with radius R. That is, ¥ = {x : ||x|lo < R}.
The label set is Y = {+1} and the loss function ¢ is defined by ¢(w, (x, y)) =
ax{0, 1 —y(w,x)}. We already know that the loss function is convex. Show
that it is R-Lipschitz.
4. (*) Convex-Lipschitz-Boundedness Is Not Sufficient for Computa-
tional Efficiency: In the next chapter we show that from the statistical

8

perspective, all convex-Lipschitz-bounded problems are learnable (in the ag-
nostic PAC model). However, our main motivation to learn such problems
resulted from the computational perspective — convex optimization is often
efficiently solvable. Yet the goal of this exercise is to show that convexity
alone is not sufficient for efficiency. We show that even for the case d = 1,
there is a convex-Lipschitz-bounded problem which cannot be learned by any
computable learner.

Let the hypothesis class be H = [0,1] and let the example domain, Z, be

170 Convex Learning Problems

the set of all Turing machines. Define the loss function as follows. For every
Turing machine T € Z, let €(0,T) = 1 if T halts on the input 0 and (0,T) = 0
if T doesn’t halt on the input 0. Similarly, let ¢(1,T) = 0 if T halts on the
input 0 and ¢(1, 7) = 1 if T doesn’t halt on the input 0. Finally, for h € (0,1),
let €(h,T) = he(0,T) + (1— Ae, T).

1. Show that the resulting learning problem is convex-Lipschitz-bounded.

2. Show that no computable algorithm can learn the problem.

13

13.1

Regularization and Stability

In the previous chapter we introduced the families of convex-Lipschitz-bounded
and convex-smooth-bounded learning problems. In this section we show that all
earning problems in these two families are learnable. For some learning problems
of this type it is possible to show that uniform convergence holds; hence they
are learnable using the ERM rule. However, this is not true for all learning
problems of this type. Yet, we will introduce another learning rule and will show
hat it learns all convex-Lipschitz-bounded and convex-smooth-bounded learning
problems.

The new learning paradigm we introduce in this chapter is called Regularized
Loss Minimization, or RLM for short. In RLM we minimize the sum of the em-

pirical risk and a regularization function. Intuitively, the regularization function

measures the complexity of hypotheses. Indeed, one interpretation of the reg-

ularization function is the structural risk minimization paradigm we discussed
in Chapter 7. Another view of regularization is as a stabilizer of the learning
algorithm. An algorithm is considered stable if a slight change of its input does

not change its output much. We will formally define the notion of stability (what
we mean by “slight change of input” and by “does not change much the out-
put”) and prove its close relation to learnability. Finally, we will show that using
the squared ¢2 norm as a regularization function stabilizes all convex-Lipschitz or

convex-smooth learning problems. Hence, RLM can be used as a general learning
tule for these families of learning problems.

Regularized Loss Minimization

Regularized Loss Minimization (RLM) is a learning rule in which we jointly min-
imize the empirical risk and a regularization function. Formally, a regularization
function is a mapping R : R? > R, and the regularized loss minimization rule
outputs a hypothesis in

argmin (Ls(w) + R(w)) . (13.1)

w

Regularized loss minimization shares similarities with minimum description length
algorithms and structural risk minimization (see Chapter 7). Intuitively, the
“complexity” of hypotheses is measured by the value of the regularization func-

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

172

13.1.1

Regularization and Stability

tion, and the algorithm balances between low empirical risk and “simpler,” or
“less complex,” hypotheses.

There are many possible regularization functions one can use, reflecting some
prior belief about the problem (similarly to the description language in Minimum
Description Length). Throughout this section we will focus on one of the most
simple regularization functions: R(w) = ||w||?, where \ > 0 is a scalar and the

norm is the €> norm, ||w|| = 1/0“, w?. This yields the learning rule:
A(S) = argmin (Ls(w) + Aljwl?) . (13.2)
w

This type of regularization function is often called Tikhonov regularization.

As mentioned before, one interpretation of Equation (13.2) is using structural
risk minimization, where the norm of w is a measure of its “complexity.” Recall
that in the previous chapter we introduced the notion of bounded hypothesis
classes. Therefore, we can define a sequence of hypothesis classes, H1 C H2 C

H3..., where H; = {w: ||w]l2 < <}. If the sample complexity of each H; depends
on i then the RLM rule is similar to the SRM rule for this sequence of nested
classes.

A different interpretation of regularization is as a stabilizer. In the next section

we define the notion of stability and prove that stable learning rules do not
overfit. But first, let us demonstrate the RLM rule for linear regression with the
squared loss.

Ridge Regression

Applying the RLM rule with Tikhonov regularization to linear regression with
the squared loss, we obtain the following learning rule:

tial
argmin | Al\w||3 + — S— =((w,x;) — yi)? |. 13.3
sami (stiri + LYS Hw. n*) (13.3)

Performing linear regression using Equation (13.3) is called ridge regression.
To solve Equation (13.3) we compare the gradient of the objective to zero and
obtain the set of linear equations

(2AmI + A)w = b,

where J is the identity matrix and A, b are as defined in Equation (9.6), namely,

m m
A= (x Xj x!) and b= Ss YiXi « (13.4)
i=1 i=1

Since A is a positive semidefinite matrix, the matrix 2\mJ + A has all its eigen-
values bounded below by 2Am. Hence, this matrix is invertible and the solution
to ridge regression becomes

w = (2AmI + A)'b. (13.5)

13.2

13.2 Stable Rules Do Not Overfit 173

In the next section we formally show how regularization stabilizes the algo-
rithm and prevents overfitting. In particular, the analysis presented in the next
sections (particularly, Corollary 13.11) will yield:

THEOREM 13.1 Let D be a distribution over © x [-1,1], where X = {x
R¢ : ||x|| < 1}. Let H = {w € R¢: ||w|| < B}. For any € € (0,1), let m
150 B?/e?. Then, applying the ridge regression algorithm with parameter
e/(3B?) satisfies

I IVian

Bm ED(A(S))] <_ min Lo(w) +e.

Remark 13.1 The preceding theorem tells us how many examples are needed
to guarantee that the expected value of the risk of the learned predictor will be
bounded by the approximation error of the class plus e. In the usual definition
of agnostic PAC learning we require that the risk of the learned predictor will
be bounded with probability of at least 1 — 6. In Exercise 1 we show how an
algorithm with a bounded expected risk can be used to construct an agnostic
PAC learner.

Stable Rules Do Not Overfit

Intuitively, a learning algorithm is stable if a small change of the input to the
algorithm does not change the output of the algorithm much. Of course, there
are many ways to define what we mean by “a small change of the input” and
what we mean by “does not change the output much”. In this section we define
a specific notion of stability and prove that under this definition, stable rules do
not overfit.

Let A be a learning algorithm, let S = (z,...,2m) be a training set of m
examples, and let A(S')) denote the output of A. The algorithm A suffers from
overfitting if the difference between the true risk of its output, Lp(A(S)), and the
empirical risk of its output, Ls(A(S)), is large. As mentioned in Remark 13.1,

throughout this chapter we focus on the expectation (with respect to the choice
of S) of this quantity, namely, Es[Lp(A(S)) — Ls(A(S))]-

We next define the notion of stability. Given the training set S and an ad-
ditional example z’, let S@ be the training set obtained by replacing the i’th
example of $ with 2’; namely, S = (21,...,2i-1, 2/, 2i41,-+-;2m). In our defi-
nition of stability, “a small change of the input” means that we feed A with S$

instead of with S. That is, we only replace one training example. We measure
the effect of this small change of the input on the output of A, by comparing
the loss of the hypothesis A(S) on z; to the loss of the hypothesis A(S) on 2.
Intuitively, a good learning algorithm will have ¢(A(S$™), z;) — €(A(S), zi) > 0,
since in the first term the learning algorithm does not observe the example 2;

while in the second term z; is indeed observed. If the preceding difference is very
large we suspect that the learning algorithm might overfit. This is because the

174

13.3

Regularization and Stability

learning algorithm drastically changes its prediction on z; if it observes it in the
training set. This is formalized in the following theorem.
THEOREM 13.2 Let D be a distribution. Let S = (2,...,2m) be an i.i.d. se-
quence of examples and let z' be another i.i.d. example. Let U(m) be the uniform
distribution over [m|. Then, for any learning algorithm,

Ell (A(S)) ~ L(A) = Es pig CAI, 20) ~ ALS), 29)
(13.6)

Proof Since S and z’ are both drawn iid. from D, we have that for every i,

E[LD(A(S))] = E [€(A(S),2")] = EM A(S), 20)

On the other hand, we can write

E{Ls(A(S))] = Ele(A(s), zi)].

Combining the two equations we conclude our proof.

When the right-hand side of Equation (13.6) is small, we say that A is a stable
algorithm — changing a single example in the training set does not lead to a
significant change. Formally,

DEFINITION 13.3 (On-Average-Replace-One-Stable) Let « : N > R be a mono-
tonically decreasing function. We say that a learning algorithm A is on-average-
replace-one-stable with rate e(m) if for every distribution D
(50) nvm AS ),%)) — €(A(S), 21)] < e(m).

Theorem 13.2 tells us that a learning algorithm does not overfit if and only
if it is on-average-replace-one-stable. Of course, a learning algorithm that does
not overfit is not necessarily a good learning algorithm — take, for example, an
algorithm A that always outputs the same hypothesis. A useful algorithm should
find a hypothesis that on one hand fits the training set (i-e., has a low empirical
risk) and on the other hand does not overfit. Or, in light of Theorem 13.2, the
algorithm should both fit the training set and at the same time be stable. As we

shall see, the parameter 2 of the RLM rule balances between fitting the training
set and being stable.

Tikhonov Regularization as a Stabilizer

In the previous section we saw that stable rules do not overfit. In this section we
show that applying the RLM rule with Tikhonov regularization, A||w||?, leads to
a stable algorithm. We will assume that the loss function is convex and that it
is either Lipschitz or smooth.

The main property of the Tikhonov regularization that we rely on is that it
makes the objective of RLM strongly convex, as defined in the following.

13.3 Tikhonov Regularization as a Stabilizer 175

DEFINITION 13.4 (Strongly Convex Functions) A function f is A-strongly con-
vex if for all w, u and a € (0,1) we have

Flaw + (1 — au) <af(w) + (1a) f(a) — Sa(1 ~ a) jw — ul?

Clearly, every convex function is 0-strongly convex. An illustration of strong
convexity is given in the following figure.

> 4a(1—a)|ju— wll?

2
ec

owt (1—ayu

The following lemma implies that the objective of RLM is (2A)-strongly con-
vex. In addition, it underscores an important property of strong convexity.
LEMMA 13.5
1. The function f(w) = A||w||? is 2\-strongly convea.

2. If f is \-strongly convex and g is convex, then f +g is A-strongly convex.
3. If f is X-strongly convex and u is a minimizer of f, then, for any w,

sw) — fa) > Sw — ul?

Proof The first two points follow directly from the definition. To prove the last
point, we divide the definition of strong convexity by a and rearrange terms to
get that

f(u+a(w —u)) — f(u)

a

< fw) ~ f(a) — 4 ~a))jw — ul?

Taking the limit a > 0 we obtain that the right-hand side converges to f(w) —
f(a) — 3||w—ul|?. On the other hand, the left-hand side becomes the derivative
of the function g(a) = f(u+a(w—u)) at a = 0. Since u is a minimizer of f,
it follows that a = 0 is a minimizer of g, and therefore the left-hand side of the

preceding goes to zero in the limit a + 0, which concludes our proof.

We now turn to prove that RLM is stable. Let S = (z1,..., 2m) be a training
set, let 2’ be an additional example, and let S = (21,...,2)-1, 2", Zit 1;-++ 52m):
Let A be the RLM rule, namely,

A(S) = argmin (Ls(w) + Aljw|?) .

176

13.3.1

Regularization and Stability

Denote fs(w) = Ls(w) + A||w|l?, and based on Lemma 13.5 we know that fs is
(2\)-strongly convex. Relying on part 3 of the lemma, it follows that for any v,

fs(v) — fs(A(S)) 2 Ally — A(S)

2. (13.7)
On the other hand, for any v and u, and for all i, we have
fs(v) — fs(u) = Ls(v) + Ally? — (Zs(u) + Allull?) (13.8)

= Lgw(v) + Allyl? — (Zs (w) + Alfull?)
_ Lv, zi) = C(u, 2) ,; e(u, 2’) — yz!)

m m
In particular, choosing v = A(S“), u = A(S), and using the fact that v mini-

mizes Lg) (w) + Al|w||?, we obtain that

(A(S), 1) = (ACS), 24) (ACS), 2) = (ACS), 2")

m

fs(A(S))—fs(A(8)) $

(13.9)
Combining this with Equation (13.7) we obtain that

A(S), 2) = (ACS), 24) | (ACS), 2") = (AS), 2)

m

xya(s)—a(s)|2 < 4

(13.10)

The two subsections that follow continue the stability analysis for either Lip-

schitz or smooth loss functions. For both families of loss functions we show that
RLM is stable and therefore it does not overfit.

Lipschitz Loss
If the loss function, @(-, z;), is p-Lipschitz, then by the definition of Lipschitzness,
&(A(S), x) = &(A(S), 21) < p|JA(S) — A(S)

. (13.11)
Similarly,

&(A(S), 2’) — (A(S), 2) < p||A(S) — A(S)]).
Plugging these inequalities into Equation (13.10) we obtain
2 < 2p\|A(S) — A(S)

‘IA(S) = ACS)

’

m
which yields
. 2p
A(S) — A(S)|| < =.
|A(s®) — a(s)|| < <%
Plugging the preceding back into Equation (13.11) we conclude that

(A(8), 3) — ACS). 2) < 3%

Since this holds for any S, z’,i we immediately obtain:

13.3.2

13.3 Tikhonov Regularization as a Stabilizer 177

COROLLARY 13.6 Assume that the loss function is convex and p-Lipschitz.
Then, the PIM rule with the regularizer X||w||? is on-average-replace-one-stable

with rate 2A It follows (using Theorem 13.2) that
g,, Ibo A(S)) - Ls(ats))] < 5%
submlPP(A(S)) ~ PsA) s yi

Smooth and Nonnegative Loss

If the loss is 6-smooth and nonnegative then it is also self-bounded (see Sec-
tion 12.1):

IVF (w)||? < 26f(w). (13.12)

We further assume that A > 28 or, in other words, that 6 < Am/2. By the

smoothness assumption we have that

&(A(S), z:)-C(A(S), 2) (VEL (A(S), 2), A(S)—A(S)) +8 .4(8)—4(8) 2.

(13.13)

Using the Cauchy-Schwartz inequality and Equation (12.6) we further obtain
that

(AS), 24) — LACS), 21)
S$ ||VEA(S), 21) | AS) — ACS) || + 2 1a(s) ~ A(S)|?

2BE(A(S), 2) ||A(S) — A(S)|| + 2 14(5) — A(S)|? .
(13.14)

By a symmetric argument it holds that,
((A(S), 2!) — (A(S), 2)
28¢(A(S®), 2) |A(S®) —

3 ;
+ acs) — a(s)|?

Plugging these inequalities into Equation (13.10) and rearranging terms we ob-
tain that

IAS) - (8) < 5 (Vasa + /qa(s@), A).

Combining the preceding with the assumption 3 < \m/2 yields

As) ~ (sy < 53 (VIA ad + (A052)

178 Regularization and Stability

Combining the preceding with Equation (13.14) and again using the assumption
B <Xm/2 yield

0(A(S), 2;) — €(A(S), 2)

< V28MAS), 2) |A(S) — A(S)I| + SI,4(9) — a(S
“(Hea fr) (eI Ven )
<¥ © (yaa + feats) =),

< 2 (e(A(S), 21) + (A(S®), 2"),

where in the last step we used the inequality (a+b)? < 3(a?+0?). Taking expecta-
tion with respect to S, 2’, i and noting that E[¢(A(S), z;)] = E[¢(A(S), z’)] =
E[Ls5(A(S))], we conclude that:

COROLLARY 13.7. Assume that the loss function is 8-smooth and nonnegative.
Then, the RLM rule with the regularizer \|w||?, where \ > 72 28 , satisfies

E [e(A(S), 21) — &(A(S), 2i)| < *? EiLs(A(S)))

Note that if for all z we have (0, z) < C, for some scalar C > 0, then for
every S,

Ls(A(S)) $ Ls(A(S)) + AJA(S)I? S$ Ls) + AlOl|? = Ls(0) < C.
Hence, Corollary 13.7 also implies that

E [¢e(A(8), x) ~ (A(S), 29] < 4880

Am

13.4 Controlling the Fitting-Stability Tradeoff

We can rewrite the expected risk of a learning algorithm as
E[L(A(S))] = BiLs(A(S))] + B[Lp(A(S)) — Ls(A(S))]- (18.18)

The first term reflects how well A(S) fits the training set while the second term
reflects the difference between the true and empirical risks of A(.S). As we have
shown in Theorem 13.2, the second term is equivalent to the stability of A. Since
our goal is to minimize the risk of the algorithm, we need that the sum of both
terms will be small.

In the previous section we have bounded the stability term. We have shown
that the stability term decreases as the regularization parameter, A, increases.
On the other hand, the empirical risk increases with \. We therefore face a


13.4 Controlling the Fitting-Stability Tradeoff 179

tradeoff between fitting and overfitting. This tradeoff is quite similar to the bias-
complexity tradeoff we discussed previously in the book.

We now derive bounds on the empirical risk term for the RLM rule. Recall
that the RLM rule is defined as A(S) = argmin,, (Ls(w) + A||w||?). Fix some
arbitrary vector w*. We have

Ls(A(S)) < Ls(A(S)) + ACS)? < Ls(w") + Allw" |.

Taking expectation of both sides with respect to S and noting that Es[Lg(w*)] =
Lp(w*), we obtain that

E[Ls(A(S))] < Lo(w*) + Aljw" |’. (13.16)
Plugging this into Equation (13.15) we obtain

E[Lp(A(S))] < Lo(w") + Allw*||? + E[Lp(A(S)) — bs(A(S))].

Combining the preceding with Corollary 13.6 we conclude:

COROLLARY 13.8 Assume that the loss function is convex and p-Lipschitz.
Then, the RLM rule with the regularization function Al|w||? satisfies

2
vw, E[Lp(A(S))} < Lo(w*) + Allwe 2 + 2

This bound is often called an oracle inequality — if we think of w* as a hy-
pothesis with low risk, the bound tells us how many examples are needed so that
A(S)) will be almost as good as w*, had we known the norm of w%*. In practice,
however, we usually do not know the norm of w*. We therefore usually tune
on the basis of a validation set, as described in Chapter 11.

We can also easily derive a PAC-like guarantee! from Corollary 13.8 for convex-
Lipschitz-bounded learning problems:

COROLLARY 13.9 Let (H, Z, 0) be a convez-Lipschitz-bounded learning problem

with parameters p,B. For any training set size m, let \ = oe. Then, the

RLM rule with the regularization function A\|w||? satisfies

E[Lo(A(S))] < min Lo(w) + pay >

22
In particular, for every « > 0, if m > sop

Egs[Lp(A(S))] < minwen Lp(w) +.

then for every distribution D,

The preceding corollary holds for Lipschitz loss functions. If instead the loss
function is smooth and nonnegative, then we can combine Equation (13.16) with
Corollary 13.7 to get:

1 Again, the bound below is on the expected risk, but using Exercise | it can be used to
derive an agnostic PAC learning guarantee.

180

13.5

13.6

Regularization and Stability

COROLLARY 13.10 Assume that the loss function is conver, B-smooth, and
nonnegative. Then, the RLM rule with the regularization function A\||w||?, for
v> 78, satisfies the following for all w*

m?

48, + 488 * eye
ziLn(a(sy] < (1+ 22) wins(a(sy) < 1<(6 + $2) (cot) + aw" IP).
For example, if we choose A = 488 we obtain from the preceding that the

expected true risk of A(S) is at most twice the expected empirical risk of A(S).
Furthermore, for this value of A, the expected empirical risk of A(S') is at most
Lo(w*) + + Siw *P.

™m.
We can also derive a learnability guarantee for convex-smooth-bounded learn-

ing problems based on Corollary 13.10.

COROLLARY 13.11 Let (H, Z,@) be a conver-smooth-bounded learning problem
with parameters 8, B. Assume in addition that (0, z) <1 for all z € Z. For any
€ € (0,1) letm> 15065? and set \ = €/(3B?). Then, for every distribution D,

E[Lp(A(S)) ] < min Lp(w) +e.

weH

Summary

We introduced stability and showed that if an algorithm is stable then it does not
overfit. Furthermore, for convex-Lipschitz-bounded or convex-smooth-bounded
problems, the RLM rule with Tikhonov regularization leads to a stable learning
algorithm. We discussed how the regularization parameter, A, controls the trade-
off between fitting and overfitting. Finally, we have shown that all learning prob-
lems that are from the families of convex-Lipschitz-bounded and convex-smooth-
bounded problems are learnable using the RLM rule. The RLM paradigm is the
basis for many popular learning algorithms, including ridge regression (which we
discussed in this chapter) and support vector machines (which will be discussed
in Chapter 15).

In the next chapter we will present Stochastic Gradient Descent, which gives us

a very practical alternative way to learn convex-Lipschitz-bounded and convex-

smooth-bounded problems and can also be used for efficiently implementing the
RLM rule.

Bibliographic Remarks

Stability is widely used in many mathematical contexts. For example, the neces-
sity of stability for so-called inverse problems to be well posed was first recognized
by Hadamard (1902). The idea of regularization and its relation to stability be-
came widely known through the works of Tikhonov (1943) and Phillips (1962).

13.7

13.7 Exercises 181

In the context of modern learning theory, the use of stability can be traced back

at least to the work of Rogers & Wagner (1978), which noted that

the sensitiv-

ity of a learning algorithm with regard to small changes in the sample controls
the variance of the leave-one-out estimate. The authors used this observation to

obtain generalization bounds for the k-nearest neighbor algorithm (see Chap-

ter 19). These results were later extended to other “local” learnin,
(see Devroye, Gyérfi & Lugosi (1996) and references therein). In ad

g algorithms
ition, practi-

cal methods have been developed to introduce stability into learning algorithms,

in particular the Bagging technique introduced by (Breiman 1996).
Over the last decade, stability was studied as a generic condition
ity. See (Kearns & Ron 1999, Bousquet & Elisseeff 2002, Kutin &
Rakhlin, Mukherjee & Poggio 2005, Mukherjee, Niyogi, Poggio &
Our presentation follows the work of Shalev-Shwartz, Shamir, Sreb:
ran (2010), who showed that stability is sufficient and necessary
They have also shown that all convex-Lipschitz-bounded learning

for learnabil-
Niyogi 2002,
Rifkin 2006).
ro & Sridha-

for learning.

problems are

learnable using RLM, even though for some convex-Lipschitz-bounded learning

problems uniform convergence does not hold in a strong sense.

Exercises

1. From Bounded Expected Risk to Agnostic PAC Learning: Let A be
an algorithm that guarantees the following: If m > m(e) then for every

distribution D it holds that

on lEe(A(S))] < min Lp(h) +€.

e Show that for every 6 € (0,1), if m > my(e€6) then with probability of at

least 1 — 6 it holds that Lp(A(S)) < minney Lp(h) + €.

Hint: Observe that the random variable Lp(A(S)) — minnex Lp(h) is

nonnegative and rely on Markov’s inequality.
e For every 6 € (0,1) let

ia(e.8) = mne/2)[loga(1/6)| + | 84/0) toa oa

Suggest a procedure that agnostic PAC learns the problem
complexity of my(e,6), assuming that the loss function is
1

w/o),

with sample
bounded by

Hint: Let k = {log,(1/6)]. Divide the data into k+1 chunks, where each
of the first k chunks is of size my(€/2) examples. Train the first k chunks

using A. On the basis of the previous question argue that the probability

that for all of these chunks we have Lp(A(S)) > minnex
at most 2~* < 6/2. Finally, use the last chunk as a validat

Lp(h) +€ is
ion set.

2. Learnability without Uniform Convergence: Let B be the unit ball of

182

Regularization and Stability

R¢, let H = B, let Z = B x {0,1}4, and let 0: Z x H > R be defined as
follows:
d

L(w, (x, a)) = Ss a; (a; — wi).

i=1

This problem corresponds to an unsupervised learning task, meaning that we
do not try to predict the label of x. Instead, what we try to do is to find the

“center of mass” of the distribution over B. However, there is a twist, modeled
by the vectors a. Each example is a pair (x, a), where x is the instance x and
@ indicates which features of x are “active” and which are “turned off.” A
hypothesis is a vector w representing the center of mass of the distribution,
and the loss function is the squared Euclidean distance between x and w, but
only with respect to the “active” elements of x.

e Show that this problem is learnable using the RLM rule with a sample

complexity that does not depend on d.

e Consider a distribution D over Z as follows: x is fixed to be some xo, and
each element of @ is sampled to be either 1 or 0 with equal probability.
Show that the rate of uniform convergence of this problem grows with
d.
Hint: Let m be a training set size. Show that if d >> 2”, then there is
a high probability of sampling a set of examples such that there exists
some j € [d] for which a; = 1 for all the examples in the training set.
Show that such a sample cannot be e-representative. Conclude that the
sample complexity of uniform convergence must grow with log(d).

e Conclude that if we take d to infinity we obtain a problem that is learnable
but for which the uniform convergence property does not hold. Compare

to the fundamental theorem of statistical learning.

3. Stability and Asymptotic ERM Are Sufficient for Learnability:

We say that a learning rule A is an AERM (Asymptotic Empirical Risk
Minimizer) with rate e(m) if for every distribution D it holds that

SnoD™

E [estas - juin (0) < em).

We say that a learning rule A learns a class H with rate e(m) if for every
distribution D it holds that

E [eta - min Lo()| <(m).

SwD™ hen
Prove the following:

THEOREM 13.12 If a learning algorithm A is on-average-replace-one-stable
with rate €\(m) and is an AERM with rate €2(m), then it learns H with rate
€1(m) + €2(m).

13.7 Exercises 183

4. Strong Convexity with Respect to General Norms:

Throughout the section we used the £2 norm. In this exercise we generalize

some of the results to general norms. Let ||-|| be some arbitrary norm, and let f
be a strongly convex function with respect to this norm (see Definition 13.4).

1.
2.

3.

Show that items 2-3 of Lemma 13.5 hold for every norm.

(*) Give an example of a norm for which item 1 of Lemma 13.5 does not
hold.

Let R(w) be a function that is (2\)-strongly convex with respect to some
norm || - ||. Let A be an RLM rule with respect to R, namely,

A(S) = argmin (Ls(w) + R(w)) .

Assume that for every z, the loss function ¢(-, z) is p-Lipschitz with respect
to the same norm, namely,
Vz, Vwyv, &(w,z) —&(v,z) < p|lw—v|| .
Prove that A is on-average-replace-one-stable with rate oF
(*) Let ¢ € (1,2) and consider the ¢,-norm

d 1/q
Iw, = (x bt) .
i=l

It can be shown (see, for example, Shalev-Shwartz (2007)) that the function

1

R(w) = Yq aay wa

is 1-strongly convex with respect to ||w]||,. Show that if g = mut then

R(w) is ( srcbay) strongly convex with respect to the ¢; norm over R¢.

14

Stochastic Gradient Descent

Recal
E-.p[l(h, z)]. We cannot

methods that depen
set S'
hypothesis

and
based on

previous

hypothesis

In this chapter we describe
which is called

notation in that chapter, we w'

a convex hypothesis class,

directly using a gradient des

irectly minimize the ris
on the unknown distribution D. So far in the book,

efine the empirical risk function Ls(h).
he value of Lg(h). For example, the ERM rule tel
pick the hypothesis that minimizes Lg(h) over the hypothesis class, H. Or, in the

Stochastic Gradient Descent (SGD).
ocus on the important family of convex learning

that the goal of learning is to minimize the risk function, Lp(h) =

function since it depends

we have discussed learning

on the empirical risk. That is, we first sample a training

Then, the learner picks a
s us to

chapter, we discussed regularized risk minimization, in which we pick a
hat jointly minimizes Ls(h) and a regularization function over h.

and analyze a rather different learning approach,

As in Chapter 12 we will
problems, and following the
ill refer to hypotheses as vectors w that come from

H. In SGD, we try to minimize the risk function Lp(w)

cent procedure. Gradient descent is an iterative

optimization procedure in which at each step we improve the solution by taking

a step along the negative of

the current point. Of course,

and since we do no

know D we also do not know

he gradient of the function to be minimized at
in our case, we are minimizing the risk function,
he gradient of Lp(w). SGD

circumvents this problem by allowing the optimization procedure to take a step

along a random direction, as

negative of the gradient. And,

expected value corresponds to the gradient is rather simple even though we do
not know the underlying distribution D.

SGD, in

regularized risk minimization

The advantage o:

that can be implemented in a

complexity as the regularized risk minimization rule. The simplicity of SGD also
allows us to use it in situations when it is not possible to apply methods that

are based on the empirical ris
We start this chapter with t
convergence rate for convex-Li

subgradient and show that gradient descent can be applied for nondifferentiable

functions as well. The core of

ong as the expected value of the direction is the
as we shall see, finding a random direction whose

he context of convex learning problems, over the
earning rule is that SGD is an efficient algorithm
few lines of code, yet still enjoys the same sample

k, but this is beyond the scope of this book.

he basic gradient descent algorithm and analyze its

pschitz functions. Next, we introduce the notion of

this chapter is Section 14.3, in which we describe

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.
Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.

ac.il/~shais/UnderstandingMachineLearning

14.1

14.1 Gradient Descent 185

the Stochastic Gradient Descent algorithm, along with several useful variants.
We show that SGD enjoys an expected convergence rate similar to the rate
of gradient descent. Finally, we turn to the applicability of SGD to learning
problems.

Gradient Descent

Before we describe the stochastic gradient descent method, we would like to
describe the standard gradient descent approach for minimizing a differentiable
convex function f(w).

The gradient of a differentiable function f : R¢ > R at w, denoted Vf(w),
is the vector of partial derivatives of f, namely, Vf(w) = (ee. ees oi).
Gradient descent is an iterative algorithm. We start with an initial value of w
(say, wi) = 0). Then, at each iteration, we take a step in the direction of the
negative of the gradient at the current point. That is, the update step is

wh) = w — nV fiw), (14.1)

where 7 > 0 is a parameter to be discussed later. Intuitively, since the gradi-
ent points in the direction of the greatest rate of increase of f around w“),
the algorithm makes a small step in the opposite direction, thus decreasing the

value of the function. Eventually, after T iterations, the algorithm outputs the
averaged vector, W = + a w"). The output could also be the last vector,
w'T), or the best performing vector, argminye(r} f(w), but taking the average
turns out to be rather useful, especially when we generalize gradient descent to

nondifferentiable functions and to the stochastic case.

Another way to motivate gradient descent is by relying on Taylor approxima-
tion. The gradient of f at w yields the first order Taylor approximation of f
around w by f(u) © f(w) + (a—w,Vf(w)). When f is convex, this approxi-
mation lower bounds f, that is,

f(u) = f(w) + (u-w, Vf(w)).

Therefore, for w close to w“) we have that f(w) ~ f(w)+(w—w, Vf(w)).
Hence we can minimize the approximation of f(w). However, the approximation

might become loose for w, which is far away from w'“). Therefore, we would like
to minimize jointly the distance between w and w and the approximation of
f around w“), If the parameter 7 controls the tradeoff between the two terms,
we obtain the update rule

1 5
wt) — argmin giiw —wO|P? +7 (f0') + (ww), vs(w'))) :
w

Solving the preceding by taking the derivative with respect to w and comparing
it to zero yields the same update rule as in Equation (14.1).

186 Stochastic Gradient Descent

Figure 14.1 An illustration of the gradient descent algorithm. The function to be

minimized is

.25(a1 + 6)? + (x2 — 8)?.

14.1.1 Analysis of GD for Convex-Lipschitz Functions

To analyze

he convergence rate of the GD algorithm, we limit ourselves to

the case of convex-Lipschitz functions (as we have seen, many problems lend
themselves easily to this setting). Let w* be any vector and let B be an upper
bound on ||w*||. It is convenient to think of w* as the minimizer of f(w), but

the analysis

hat follows holds for every w*.

We would
with respect

ike to obtain an upper bound on the suboptimality of our solution
to w*, namely, f(w) — f(w*), where w = >a w), From the

definition of w, and using Jensen’s inequality, we have that

T
F(w) ~ fw") = f (1d6°) ~ fw")
t=1
1 T
< Fd (fw) — FO")

t

1

Il
Ss)
Ma

(sew) - fw"). (14.2)

t

IL
»

For every t, because of the convexity of f, we have that

Combining t

Pw) — fow') < (wO —w", Vf(w')). (14.3)
he preceding we obtain

f(w) — fw") < 2

SI

T
Sow —w* Vi (w"))).
t=1

To bound the right-hand side we rely on the following lemma:

14.1 Gradient Descent 187

LEMMA 14.1 Let vi,...,vr be an arbitrary sequence of vectors. Any algorithm
with an initialization w) =0 and an update rule of the form

wt!) — w — nv, (14.4)

satisfies
T * 1/2
Sow!) —w*,v)) < x ry

t=1

‘sts

T
+3d! {ve l?- (14.5)

In parNeular: for every B,p > 0, if for allt we have that ||v:|| < p and if we set

n= or: then for every w* with ||w*|| < B we have

Vr

Proof Using algebraic manipulations (completing the square), we obtain:

T
aw w*,vy) < Be
=1

1
(w") —w*, vi) = 7 —w*,7Vt)
1 eo
= gy (lle = we vel? + [lw = we"? + oP vel?)
1 5
= 5 (Iw) — w" + [pw — wl?) + Tliv

where the last equality follows from the definition of the update rule. Summing
the equality over t, we have

Tv Tv T
1
Dow wera) = 35D (lw — wr wl — wr?) +5 9 Ive
t=1 t=1 t=1
(14.6)
The first sum on the right-hand side is a telescopic sum that collapses to
Iw) —w* ||? jw +) — w* |?.
Plugging this in Equation (14.6), we have
T 1 ” Tv
Dew = wrvi) =< (\lw = w" |)? = wD — w" |?) + 59 lvell?
t=1 ” t=1
1 n r
< a w+ 2S Iivil?
t=1

T
ul
= gl + 5D Il?

where the last equality is due to the definition w“) = 0. This proves the first
part of the lemma (Equation (14.5)). The second part follows by upper bounding

||w*|| by B, ||vel] by p, dividing by T, and plugging in the value of 7.


188 Stochastic Gradient Descent

Lemma 14.1 applies to the GD algorithm with v; = Vf(w™). As we will
show later in Lemma 14.7, if f is p-Lipschitz, then ||V f(w“)|| < p. We therefore
satisfy the lemma’s conditions and achieve the following corollary:
COROLLARY 14.2 Let f be a convex, p-Lipschitz function, and let w* € argminyy,.wij<py [(w)-
If we run the GD algorithm on f for T steps with n = Ae: then the output

vector W satisfies

f(w) — fw") <

ae

Furthermore, for every € > 0, to achieve f(w)— f(w*) <, it suffices to run the
GD algorithm for a number of iterations that satisfies

2 2
ee

T

e

14.2 Subgradients

The GD algorithm requires that the function f be differentiable. We now gener-
alize the discussion beyond differentiable functions. We will show that the GD
algorithm can be applied to nondifferentiable functions by using a so-called sub-
gradient of f(w) at w"), instead of the gradient.

To motivate the definition of subgradients, recall that for a convex function f,
the gradient at w defines the slope of a tangent that lies below f, that is,

Vu, f(u) > f(w) + (u—w, Vf(w)). (14.7)

An illustration is given on the left-hand side of Figure 14.2.

The existence of a tangent that lies below f is an important property of convex
functions, which is in fact an alternative characterization of convexity.

LEMMA 14.3 Let S' be an open convezx set. A function f : S — R is convex iff
for every w € S there exists v such that

Vue S, f(u) > f(w) + (u-w,v). (14.8)

The proof of this lemma can be found in many convex analysis textbooks (e.g.,
(Borwein & Lewis 2006)). The preceding inequality leads us to the definition of
subgradients.

DEFINITION 14.4 (Subgradients) A vector v that satisfies Equation (14.8) is
called a subgradient of f at w. The set of subgradients of f at w is called the
differential set and denoted Of (w).

An illustration of subgradients is given on the right-hand side of Figure 14.2.
For scalar functions, a subgradient of a convex function f at w is a slope of a
line that touches f at w and is not above f elsewhere.

14.2.1

14.2 Subgradients 189

Figure 14.2 Left: The right-hand side of Equation (14.7) is the tangent of f at w. For
a convex function, the tangent lower bounds f. Right: Illustration of several
subgradients of a nondifferentiable convex function.

Calculating Subgradients

How do we construct subgradients of a given convex function? If a function is
differentiable at a point w, then the differential set is trivial, as the following
claim shows.

CLAIM 14.5 If f is differentiable at w then Of(w) contains a single element —
the gradient of f atw, Vf(w).

Example 14.1 (The Differential Set of the Absolute Function) Consider the
absolute value function f(a) = |x|. Using Claim 14.5, we can easily construct
the differential set for the differentiable parts of f, and the only point that
requires special attention is zo = 0. At that point, it is easy to verify that the
subdifferential is the set of all numbers between —1 and 1. Hence:
{1} ife>0
Of(~)=4{-1} ifa<0
[-1,1] ifx=0
For many practical uses, we do not need to calculate the whole set of subgra-

dients at a given point, as one member of this set would suffice. The following
claim shows how to construct a sub-gradient for pointwise maximum functions.

CLAIM 14.6 Let g(w) = maxjep,|gi(w) for r conver differentiable functions
Ji, +++, gr. Given some w, let j € argmax; gi(w). Then Vgj(w) € Og(w).

Proof Since g; is convex we have that for all u
gj(u) > 9j(w) + (u—w, Vg;(w)).
Since g(w) = g;(w) and g(u) > g;(u) we obtain that
g(a) 2 g(w) + (u— w, Vgj(w)),

which concludes our proof.


190

14.2.2

14.2.3

Stochastic Gradient Descent

Example 14.2 (A Subgradient of the Hinge Loss) Recall the hinge loss function
from Section 12.3, f(w) = max{0,1— y(w, x)} for some vector x and scalar y.
To calculate a subgradient of the hinge loss at some w we rely on the preceding
claim and obtain that the vector v defined in the following is a subgradient of
the hinge loss at w:

0 if 1— y(w, x) <0
v=
-yx if l1—y(w, x) >0

Subgradients of Lipschitz Functions
Recall that a function f : A > R is p-Lipschitz if for all u,v € A
IF(u) = f(v)| < plju—vI).
The following lemma gives an equivalent definition using norms of subgradients.

LEMMA 14.7 Let A be a convex open set and let f : A + R be a convex function.
Then, f is p-Lipschitz over A iff for all w € A and v € Of(w) we have that
IIvll < e-

Proof Assume that for all v € Of(w) we have that ||v|| < p. Since v € Of(w)
we have

f(w) — f(a) < (v,w —u).
Bounding the right-hand side using Cauchy-Schwartz inequality we obtain
f(w) — fu) < (v, w—u) <|IvII lw — ul] < pilw — ul.
An analogous argument can show that f(u) — f(w) < p||w — ul]. Hence f is
p-Lipschitz.

Now assume that f is p-Lipschitz. Choose some w € A,v € Of(w). Since A
is open, there exists € > 0 such that u = w + ev/||v|| belongs to A. Therefore,
(u — w, v) =e||v|| and ||u — w|| = ¢. From the definition of the subgradient,

f(u) — f(w) > (v,u—w) = ely.
On the other hand, from the Lipschitzness of f we have
pe=p|lu—wl| > f(u) — fw).

Combining the two inequalities we conclude that ||v|| < p.

Subgradient Descent

The gradient descent algorithm can be generalized to nondifferentiable functions
by using a subgradient of f(w) at w™, instead of the gradient. The analysis of
the convergence rate remains unchanged: Simply note that Equation (14.3) is
true for subgradients as well.

14.3

14.3.1

14.3 Stochastic Gradient Descent (SGD) 191

Figure 14.3 An illustration of the gradient descent algorithm (left) and the stochastic
gradient descent algorithm (right). The function to be minimized is

1.25(a + 6)? + (y — 8). For the stochastic case, the black line depicts the averaged
value of w.

Stochastic Gradient Descent (SGD)

In stochastic gradient descent we do not require the update direction to be based
exactly on the gradient. Instead, we allow the direction to be a random vector
and only require that its expected value at each iteration will equal the gradient
direction. Or, more generally, we require that the expected value of the random
vector will be a subgradient of the function at the current vector.

Stochastic Gradient Descent (SGD) for minimizing
f(w)

parameters: Scalar 7 > 0, integer T > 0

initialize: w =0

for t=1,2,...,T
choose v; at random from a distribution such that E[v, |w] € 0f(w™)
update wt) = w — nv,

output w= 4 vw)

An illustration of stochastic gradient descent versus gradient descent is given
in Figure 14.3. As we will see in Section 14.5, in the context of learning problems,
it is easy to find a random vector whose expectation is a subgradient of the risk

function.

Analysis of SGD for Convex-Lipschitz-Bounded Functions

Recall the bound we achieved for the GD algorithm in Corollary 14.2. For the
stochastic case, in which only the expectation of v; is in 0f(w")), we cannot
directly apply Equation (14.3). However, since the expected value of v; is a

192 Stochastic Gradient Descent

subgradient of f at w™, we can still derive a similar bound on the expected
output of stochastic gradient descent. This is formalized in the following theorem.

THEOREM 14.8 Let B,p > 0. Let f be a convex function and let w* € argminy,|iw\|<p f(W)-

Assume that SGD is run for T iterations with n =
all t, ||vil| < p with probability 1. Then,

Bp
vl
Therefore, for any € > 0, to achieve E[f(w)] — f(w*) < «¢, it suffices to run the

SGD algorithm for a number of iterations that satisfies

2 2
p> Be.
>

E(f(w)] — f(w*) <

Proof Let us introduce the notation vj., to denote the sequence vj,...,V¢.

Taking expectation of Equation (14.2), we obtain

E [f(w) — fw") < EB

Vir

4S (Fw) - sow") .

Since Lemma 14.1 holds for any sequence v1, V2,...v7, it applies to SGD as well.
By taking expectation of the bound in the lemma we have

T
1 B
T y (w) — w*, v;) pe
t=1

E SR (14.9)

It is left to show that

Vir Vir

rw ~~ v9 , (14.10)

t=1

RF (Ww) - 19] < —E

which we will hereby prove.
Using the linearity of the expectation we have

1 T
i Vw — wt vi)
t=1

Next, we recall the law of total expectation: For every two random variables a, 3,
and a function g, Eq[g(a)] = Eg Eq[g(a)|]. Setting a = vi4 and 8 = vi..—-1 we
get that

T
1
== (t) _ wy
= TE lw w*,vi)].

E [(w) — w*,v,)] = E [wl — w*, vy)]

Vit Vit

EE [(w — w*, vi) | visa] -

Virt-1 Vict

Once we know vj.;—1, the value of w) is not random any more and therefore

EE [(w —w*,vi)|viea] = E (w® — w*, Efv: | vii) -
ve

Vist-1 Vit Vist-1

14.4

14.4.1

14.4 Variants 193

Since w“) only depends on v1.;—-1 and SGD requires that Ey, [v; | w] € 0f(w)
we obtain that Ey, [vz | vi:—1] € af(w), Thus,

E(w —w*Elve|vieal) > E [f(w') — f(w*)).

Vit-1 Virt-1
Overall, we have shown that
E [(w® —w*,v)] > E [f(w) — f(w’)]
vur Vist-1
= E [f(w™) - fw*)] .
vir

Summing over t, dividing by 7’, and using the linearity of expectation, we get

that Equation (14.10) holds, which concludes our proof.

Variants

In this section we describe several variants of Stochastic Gradient Descent.

Adding a Projection Step

In the previous analyses of the GD and SGD algorithms, we required that the
norm of w* will be at most B, which is equivalent to requiring that w* is in the
set H = {w: ||w|| < B}. In terms of learning, this means restricting ourselves to
a B-bounded hypothesis class. Yet any step we take in the opposite direction of
the gradient (or its expected direction) might result in stepping out of this bound,
and there is even no guarantee that w satisfies it. We show in the following how
to overcome this problem while maintaining the same convergence rate.

The basic idea is to add a projection step; namely, we will now have a two-step
update rule, where we first subtract a subgradient from the current value of w
and then project the resulting vector onto H. Formally,

L.. wits) = wi!) — nVt
2. wt) = argminy ¢7 ||w — witt2) ||

The projection step replaces the current value of w by the vector in H closest
to it.

Clearly, the projection step guarantees that w“) € H for all t. Since 1 is
convex this also implies that w € H as required. We next show that the analysis
of SGD with projections remains the same. This is based on the following lemma.

LEMMA 14.9 (Projection Lemma) Let H be a closed convex set and let v be the
projection of w onto H, namely,

v = argmin ||x — w||?.
xEH

194

14.4.2

Stochastic Gradient Descent

Then, for every u € H,

Ilw -

ull? — |v — ul? > 0.

Proof By the convexity of H, for every a € (0, 1) we have that v+a(u—v) € H.
Therefore, from the optimality of v we obtain

IIv — wl)? < |v +a(u—v) — |)?

=Iv-wll
Rearranging, we obtain

2(v—w

24 2a(v —w,u—v) +a?|/u—v|]?.

,u—v) >-allu— vl’.

Taking the limit a > 0 we get that

(v-—w,u-—v)>0.

Therefore,

Iw — ul? = |Iw—vtv—ul?

Iw — v2 + |v — ul? +20 —w, uv)

2 ||v —ull?.

Equipped with the preceding
to the case in which we add pro.
note that for every t,

|jw HD — wr ||? — |) — we

= Iw) — we |]? — |Jwlt

< |w2) — w* |)? — |jw

jection steps on a closed and convex set. Simply

lemma, we can easily adapt the analysis of S@D

?
2D) — whl)? + pw) — we]? — Iw! — wl?

—w'* ||’.

Therefore, Lemma 14.1 holds w!
of the analysis follows directly.

Variable Step Size

hen we add projection steps and hence the rest

Another variant of SGD is decreasing the step size as a function of t. That is,

rather than updating with a constant 7, we use 7. For instance, we can set

m= wt and achieve a bound similar to Theorem 14.8. The idea is that when

we are closer to the minimum of the function, we take our steps more carefully,

so as not to “overshoot” the minimum.

14.4.3

14.4.4

14.4 Variants 195

Other Averaging Techniques

We have set the output vector to be w = + a w(), There are alternative
approaches such as outputting w for some random t € [t], or outputting the
average of w'") over the last aT iterations, for some a € (0,1). One can also take
a weighted average of the last few iterates. These more sophisticated averaging
schemes can improve the convergence speed in some situations, such as in the
case of strongly convex functions defined in the following.

Strongly Convex Functions*

In this section we show a variant of SGD that enjoys a faster convergence rate for
problems in which the objective function is strongly convex (see Definition 13.4
of strong convexity in the previous chapter). We rely on the following claim,
which generalizes Lemma 13.5.

CLAIM 14.10 If f is A-strongly convex then for every w,u and v € Of(w) we
have

(w—u,v) > f(w)— f(a) + 3\lw-ul?.

The proof is similar to the proof of Lemma 13.5 and is left as an exercise.

SGD for minimizing a A-strongly convex function

Goal: Solve minwex, f(w)
parameter: T
initialize: w“) =0

Choose a random vector v; s.t. E[v,|w] € 0f(w)
Set m = 1/(At)

Set wtt2) = wi) — mV

Set wt) = arg minyex ||w — witt2) \|?

output: w= 47, w

THEOREM 14.11 Assume that f is -strongly convex and that E{||vz||?] < p?.
Let w* € argmin,,<z, f(w) be an optimal solution. Then,
2
Elf (w)] — sw") < 2 (0 + loa(Z)).
Proof Let V = Efv;|w]. Since f is strongly convex and V“ is in the
subgradient set of f at w“) we have that
(w —w*, VO) > fiw) — f(w*) + 3 lw — we? . (14.11)
Next, we show that
(0) yy 2 — pgp (tL) _ yy 2
fw weg) < Elle =wil?= Iw) WP) ee ayaa

2m

196

14.5

14.5.1

Stochastic Gradient Descent

Since w+) is the projection of w+) onto H, and w* € H we have that
\|w+2) — w* |)? > |jwt) — w*||?. Therefore,

sw) — wr]? = Jw) — wr? > wl) — we — Iw 2) — we
= 2m(w) —w*,ve) — ne llvill?

Taking expectation of both sides, rearranging, and using the assumption E[||v;||?] <
p” yield Equation (14.12). Comparing Equation (14.11) and Equation (14.12) and
summing over t we obtain

T
ELF (w)] = Fow"))
t=1
*|/? Iw) w* |?

. [Iw — w* |)? — ~ d |g (t) x12 pe z
<E}>>( = — Zw —w'l?)] +29 me
t=1

Next, we use the definition m = 1/(At) and note that the first sum on the
right-hand side of the equation collapses to —AT||w'?+)) — w*||? < 0. Thus,

T ; fe T
Lewy] = Fw") < Y

The theorem follows from the preceding by dividing by T and using Jensen’s

<fa + log(T)).

“ae
%
>

inequality.

Remark 14.3 Rakhlin, Shamir & Sridharan (2012) derived a convergence rate
in which the log(T) term is eliminated for a variant of the algorithm in which
we output the average of the last T/2 iterates, w = 4 eres w, Shamir &
Zhang (2013) have shown that Theorem 14.11 holds even if we output w = w'7).

Learning with SGD

We have so far introduced and analyzed the SGD algorithm for general convex
functions. Now we shall consider its applicability to learning tasks.

SGD for Risk Minimization
Recall that in learning we face the problem of minimizing the risk function

Lo(w) = E, lew, 2)

We have seen the method of empirical risk minimization, where we minimize the
empirical risk, L3(w), as an estimate to minimizing Lp(w). SGD allows us to
take a different approach and minimize Lp(w) directly. Since we do not know
D, we cannot simply calculate Vip(w™) and minimize it with the GD method.
With SGD, however, all we need is to find an unbiased estimate of the gradient of

14.5 Learning with SGD 197

Lp(w), that is, a random vector whose conditional expected value is VEp(w™).
We shall now see how such an estimate can be easily constructed.

For simplicity, let us first consider the case of differentiable loss functions.
Hence the risk function Lp is also differentiable. The construction of the random
vector v; will be as follows: First, sample z ~ D. Then, define v; to be the
gradient of the function ¢(w, z) with respect to w, at the point w“). Then, by
the linearity of the gradient we have

E[y:;w)] = EE vew, 2aj= VE ew, z))=VLo(w™). (14.13)
The gradient of the loss function £(w, z) at w\) is therefore an unbiased estimate
of the gradient of the risk function Lp(w™) and is easily constructed by sampling
a single fresh example z ~ D at each iteration t.

The same argument holds for nondifferentiable loss functions. We simply let
v, be a subgradient of &(w, z) at w. Then, for every u we have

E(u, z) — &(w, z) > (u—w, vi).

Taking expectation on both sides with respect to z ~ D and conditioned on the
value of w\) we obtain

Lp(u) ~ Lp(w) = Ele(u, 2) — ew", Jw)
E[(u — w, v,)|w]

(u— w, Blv,|w).

Vv

It follows that E[v;|w] is a subgradient of Lp(w) at w™.
To summarize, the stochastic gradient descent framework for minimizing the
risk is as follows.

Stochastic Gradient Descent (SGD) for minimizing
Lp(w)

parameters: Scalar 7 > 0, integer T > 0
initialize: w“) =0
for t=1,2,...,T7

sample z ~ D

pick v; € 0¢(w™), z)

update w+) = w — nv,

output w= 47, w)

We shall now use our analysis of SGD to obtain a sample complexity anal-
ysis for learning convex-Lipschitz-bounded problems. Theorem 14.8 yields the
following:

COROLLARY 14.12 Consider a convez-Lipschitz-bounded learning problem with
parameters p,B. Then, for every € > 0, if we run the SGD method for minimizing

198

14.5.2

Stochastic Gradient Descent

Lp(w) with a number of iterations (i.e., number of examples)

2 42
p> Be
2-2

and with n = Vr then the output of SGD satisfies
E[Lp(w)] < min Lp(w) +.
weH

It is interesting to note that the required sample complexity is of the same order
of magnitude as the sample complexity guarantee we derived for regularized loss
minimization. In fact, the sample complexity of SGD is even better than what
we have derived for regularized loss minimization by a factor of 8.

Analyzing SGD for Convex-Smooth Learning Problems

In the previous chapter we saw that the regularized loss minimization rule also
learns the class of convex-smooth-bounded learning problems. We now show that
the SGD algorithm can be also used for such problems.

THEOREM 14.13 Assume that for all z, the loss function €(-,z) is convex, B-
smooth, and nonnegative. Then, if we run the SGD algorithm for minimizing
Lp(w) we have that for every w*,

- 1 «Iwi?
E{Lp(w)]| < i- 78 (ow y+ ) .

2nT

Proof Recall that if a function is 6-smooth and nonnegative then it is self-
bounded:

IV f(w)||? < 28 f(w).
To analyze SGD for convex-smooth problems, let us define 21,..., 27 the random
samples of the SGD algorithm, let f;(-) = ¢(-, z:), and note that v, = Vfi(w).
For all t, f; is a convex function and therefore f,(w™)— f;(w*) < (vi, w —w*),
Summing over ¢ and using Lemma 14.1 we obtain

T

SoHiw!) = fiw") < Dwr wl we) < HE

t=1 t=1

*|/?

ne
tad lal

Combining the preceding with the self-boundedness of f; yields

T
iw i‘

Siw) = filw*)) <

t=1

+ wo cw!”

Dividing by T and rearranging, we obtain

Loewe) (1S ey, wl?
To fw Sip ZL fw") 4 nT .

Next, we take expectation of the two sides of the preceding equation with respect


14.5.3

14.5 Learning with SGD 199

to z1,..., 27. Clearly, E[f;(w*)] = Lp(w*). In addition, using the same argument
as in the proof of Theorem 14.8 we have that

E

ly ®
m fi(w)) =E
renew

7 Low > E[Lp(w)].

Combining all we conclude our proof.

As a direct corollary we obtain:

COROLLARY 14.14 Consider a convex-smooth-bounded learning problem with
parameters 8,B. Assume in addition that (0,2) <1 for all z € Z. For every

e>0, setn= EIR Then, running SGD with T > 12B?8/e? yields

E[Lp(w)] < min Lp(w) +€.

SGD for Regularized Loss Minimization

We have shown that SGD enjoys the same worst-case sample complexity bound
as regularized loss minimization. However, on some distributions, regularized loss

minimization may yield a better solution. Therefore, in some cases we may want
to solve the optimization problem associated with regularized loss minimization,

namely,!
Xr
min (Fim? + Ls(w)) . (14.14)
w 2

Since we are dealing with convex learning problems in which the loss function is
convex, the preceding problem is also a convex optimization problem that can
be solved using SGD as well, as we shall see in this section.

Define f(w) = 3||w||? + Ls(w). Note that f is a \-strongly convex function;
therefore, we can apply the SGD variant given in Section 14.4.4 (with H = R?).
To apply this algorithm, we only need to find a way to construct an unbiased
estimate of a subgradient of f at w). This is easily done by noting that if
we pick z uniformly at random from $, and choose v; € 0f(w“,z) then the
expected value of Aw) + v; is a subgradient of f at w“).

To analyze the resulting algorithm, we first rewrite the update rule (assuming

1 We divided \ by 2 for convenience.

200

14.6

14.7

Stochastic Gradient Descent

that H = R¢ and therefore the projection step does not matter) as follows

1
witt)) = wit) — a (aw + vt)

1 1
= (1 — i) wi!) — swal

t
1
= Gv (14.15)

If we assume that the loss function is p-Lipschitz, it follows that for all t we have
|v: || < p and therefore ||/Aw“)|| < p, which yields

Aw + vil] < 2p.

Theorem 14.11 therefore tells us that after performing T iterations we have that

2
ELs(w)] — fw") < $(1 + tog(7)).

Summary

We have introduced the Gradient Descent and Stochastic Gradient Descent algo-
rithms, along with several of their variants. We have analyzed their convergence
rate and calculated the number of iterations that would guarantee an expected
objective of at most € plus the optimal objective. Most importantly, we have
shown that by using SGD we can directly minimize the risk function. We do
so by sampling a point i.i.d from D and using a subgradient of the loss of the
current hypothesis w“) at this point as an unbiased estimate of the gradient (or
a subgradient) of the risk function. This implies that a bound on the number of
iterations also yields a sample complexity bound. Finally, we have also shown
how to apply the SGD method to the problem of regularized risk minimization.

In future chapters we show how this yields extremely simple solvers to some
optimization problems associated with regularized risk minimization.

Bibliographic Remarks

SGD dates back to Robbins & Monro (1951). It is especially effective in large
scale machine learning problems. See, for example, (Murata 1998, Le Cun 2004,
Zhang 2004, Bottou & Bousquet 2008, Shalev-Shwartz, Singer & Srebro 2007,
Shalev-Shwartz & Srebro 2008). In the optimization community it was studied

14.8 Exercises 201

in the context of stochastic optimization. See, for example, (Nemirovski & Yudin
1978, Nesterov & Nesterov 2004, Nesterov 2005, Nemirovski, Juditsky, Lan &
Shapiro 2009, Shapiro, Dentcheva & Ruszczyniski 2009).

The bound we have derived for strongly convex function is due to Hazan,
Agarwal & Kale (2007). As mentioned previously, improved bounds have been
obtained in Rakhlin et al. (2012).

14.8 Exercises

1. Prove Claim 14.10. Hint: Extend the proof of Lemma 13.5.

2. Prove Corollary 14.14.

3. Perceptron as a subgradient descent algorithm: Let S = ((x1, y1),---;(Km; Ym)) €
(R¢ x {£1})™. Assume that there exists w € R¢ such that for every i € [m]
we have y;(w,x;) > 1, and let w* be a vector that has the minimal norm

among all vectors that satisfy the preceding requirement. Let R = max; ||x;]|.
Define a function
f(w) = max (1 — yi (w, xi).
ie[m]

e Show that minw:|jw\j<|jw*|| f(w) = 0 and show that any w for which f(w) <
1 separates the examples in S.

e Show how to calculate a subgradient of f.

e Describe and analyze the subgradient descent algorithm for this case. Com-
pare the algorithm and the analysis to the Batch Perceptron algorithm
given in Section 9.1.2.

4. Variable step size (*): Prove an analog of Theorem 14.8 for SGD with a
variable step size, 7, = wa

15

15.1

Support Vector Machines

In this chapter and the next we discuss a very useful machine learning tool: the
support vector machine paradigm (SVM) for learning linear predictors in high
dimensional feature spaces. The high dimensionality of the feature space raises
both sample complexity and computational complexity challenges.

The SVM algorithmic paradigm tackles the sample complexity challenge by
searching for “large margin” separators. Roughly speaking, a halfspace separates
a training set with a large margin if all the examples are not only on the correct
side of the separating hyperplane but also far away from it. Restricting the
algorithm to output a large margin separator can yield a small sample complexity
even if the dimensionality of the feature space is high (and even infinite). We
introduce the concept of margin and relate it to the regularized loss minimization
paradigm as well as to the convergence rate of the Perceptron algorithm.

In the next chapter we will tackle the computational complexity challenge
using the idea of kernels.

Margin and Hard-SVM

Let S = (x1, 41),---,(Xm;Ym) be a training set of examples, where each x; € R¢

and y; € {+1}. We say that this training set is linearly separable, if there exists
a halfspace, (w,b), such that y; = sign((w,x;) + 6) for all i. Alternatively, this
condition can be rewritten as

Vi € [ml], yi((w, xi) +d) > 0.

All halfspaces (w, b) that satisfy this condition are ERM hypotheses (their 0-1
error is zero, which is the minimum possible error). For any separable training
sample, there are many ERM halfspaces. Which one of them should the learner
pick?

Consider, for example, the training set described in the picture that follows.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

15.1 Margin and Hard-SVM

203

While both the dashed-black an
amples, our intuition would probably lead us to prefer the b

hyperplane has a large margin,

he error), regardless of the Euc
Hard-SVM is the learning rul
separates the training set with t

he parameters defining the hal

CLAIM 15.1
(w, b) where ||w|| = 1 is |(w,x)

he green one. One way to formali
The margin of a hyperplane wi

we slightly perturb each instance
We will see later on that the true error o:
of the margin it has over the tra:

he largest

solid-green hy

ze this in

h respect to a

minimal distance between a point in the training set and

hen it wil
e.
Fa hal:

idean dimension

possib:

fspace.

+.

ining sample (the larger the

perplanes separate the four ex-
ack hyperplane over

uition is using the concept of margin.

is defined to be the
he hyperplane. If a

raining set

still separate the training set even if

space can be bounded in terms

margin, the smaller

in which this halfspace resides.

le in which we return an ERM hyperplane that

le margin. To define Hard-SVM

formally, we first express the distance between a point x to a hyperplane using

The distance between a point x and the hyperplane defined by

Proof The distance between a point x and the hyperplane is defined as

min{||x — v|| : (w,v) + b = O}.

Taking v = x — ((w, x) + b)w we have that

(w,v) +b = (w,x) — ((w,x) + b)||w||? +6 =0,

and

Ik-v

|(w, x) + 8] [lw]

|(w,x) 4

dl.

Hence, the distance is at most |(w,x) + b|. Next, take any other point u on the

hyperplane, thus (w, u) + b= 0.

IIx — ul?

We have

Ix-vtv—-ul?

[x — vl? + |lv — ull? +

where the last equality

|x—v?,

2(x —v,v—u)

|x — v|? +2(x-—v,v—u)

|x — v||? + 2((w,x) + b)(w, v — u)

is because (w,v) = (w,u) = —b. Hence, the distance

204

Support Vector Machines

between x and u is at least the distance between x and v, which concludes our

proof.

On the basis of the preceding claim, the closest point in the training set to the
separating hyperplane is minjejm) |(w, xi) + b|. Therefore, the Hard-SVM rule is

argmax min |(w,x;)+)| st. Vi, yi((w,xi:) +b) > 0.
(w,b):||wil=1 #€lm]

Whenever there is a solution to the preceding problem (i.e., we are in the sepa-
rable case), we can write an equivalent problem as follows (see Exercise 1):

argmax min y;((w,x;) +). (15.1)
(w,b):|[w{]=1  7€[m]

Next, we give another equivalent formulation of the Hard-SVM rule as a quadratic
optimization problem.!

Hard-SVM

input: (x1, y1),---,(Xm, Ym)
solve:

(wo, bo) = argmin ||wl|? s.t. Vi, yi((w,x:) +b) >1 (15.2)

(w,b)
~ a bi
output: W= “2, b= _%
P Twoll’ Two

The lemma that follows shows that the output of hard-SVM is indeed the
separating hyperplane with the largest margin. Intuitively, hard-SVM searches
for w of minimal norm among all the vectors that separate the data and for

which |(w,x;) + b| > 1 for all i. In other words, we enforce the margin to be 1,
but now the units in which we measure the margin scale with the norm of w.
Therefore, finding the largest margin halfspace boils down to finding w whose
norm is minimal. Formally:

LEMMA 15.2 The output of Hard-SVM is a solution of Equation (15.1).

Proof Let (w*,b*) be a solution of Equation (15.1) and define the margin
achieved by (w*,b*) to be 7* = minje{m) yi((w*,xi) + b*). Therefore, for all
i we have

yi((w*, xi) +0") > 9*

or equivalently

yi((S>. xi) + =) 21.

w ; =) satisfies the conditions of the quadratic optimization

Hence, the pair (

1 A quadratic optimization problem is an optimization problem in which the objective is a
convex quadratic function and the constraints are linear inequalities.

15.1.1

15.1.2

15.1 Margin and Hard-SVM 205

problem given in Equation (15.2). Therefore, ||wol| < ||%=| = aoe It follows that
for all 2,
in (se 2) +) = a gi((wo, xi) +B) > 29".
II woll II woll
Since ||w|| = 1 we obtain that (w, 6) is an optimal solution of Equation (15.1).

The Homogenous Case

It is often more convenient to consider homogenous ha
that pass through the origin and are thus defined by s:
term 0 is set to be zero. Hard-SVM for homogenous hal

min ||w||? s.t. Vi, yi(w, xi)
w

As we discussed in Chapter 9, we can reduce the problem of learning nonhomogenous

halfspaces to the problem of learning homogenous hal:

fspaces, namely, halfspaces
ign((w,x)), where the bias
fspaces amounts to solving

>1. (15.3)

spaces by adding one more

feature to each instance of x;, thus increasing the dimension to d+ 1.
Note, however, that the optimization problem given in Equation (15.2) does
not regularize the bias term b, while if we learn a homogenous halfspace in R¢+!

using Equation (15.3) then we regularize the bias term (i.e., the d+ 1 component

of the weight vector) as well. However, regularizing b usually does not make a

significant difference to the sample complexity.

The Sample Complexity of Hard-SVM

Recall that the VC-dimension of halfspaces in R@ is d+ 1. It follows that the
sample complexity of learning halfspaces grows with the dimensionality of the

problem. Furthermore, the fundamental theorem of learning tells us that if the
number of examples is significantly smaller than d/e then no algorithm can learn
an e-accurate halfspace. This is problematic when d is very large.

To overcome this problem, we will make an additional assumption on the
underlying data distribution. In particular, we will define a “separability with
margin y” assumption and will show that if the data is separable with margin
7 then the sample complexity is bounded from above by a function of 1/77. It
follows that even if the dimensionality is very large (or even infinite), as long as
the data adheres to the separability with margin assumption we can still have a

small sample complexity. There is no contradiction to the lower bound given in
the fundamental theorem of learning because we are now making an additional
assumption on the underlying data distribution.

Before we formally define the separability with margin assumption, there is a

scaling issue we need to resolve. Suppose that a training set S = (x1, y1),---,(Xm+Ym)

is separable with a margin y, namely, the maximal objective value of Equa-
tion (15.1) is at least 7. Then, for any positive scalar a > 0, the training set

206

15.2

Support Vector Machines

S” = (ax1,y1),---,(@Xm, Ym) is separable with a margin of ay. That is, a sim-
ple scaling of the data can make it separable with an arbitrarily large margin. It
follows that in order to give a meaningful definition of margin we must take into
account the scale of the examples as well. One way to formalize this is using the
definition that follows.

DEFINITION 15.3. Let D be a distribution over R¢ x {+1}. We say that D is
separable with a (y,p)-margin if there exists (w*,b*) such that ||w*|| = 1 and
such that with probability 1 over the choice of (x, y) ~ D we have that y((w*, x)+
b*) > and ||x|| < p. Similarly, we say that D is separable with a (7, p)-margin

using a homogenous halfspace if the preceding holds with a halfspace of the form
(w*,0).

In the advanced part of the book (Chapter 26), we will prove that the sample
complexity of Hard-SVM depends on (p/y)? and is independent of the dimension
d. In particular, Theorem 26.13 in Section 26.3 states the following:

THEOREM 15.4 Let D be a distribution over R¢ x {+1} that satisfies the (7, p)-
separability with margin assumption using a homogenous halfspace. Then, with
probability of at least 1—6 over the choice of a training set of size m, the 0-1
error of the output of Hard-SVM is at most

(seh + je. 2/8)

Remark 15.1 (Margin and the Perceptron) In Section 9.1.2 we have described
and analyzed the Perceptron algorithm for finding an ERM hypothesis with
respect to the class of halfspaces. In particular, in Theorem 9.1 we upper bounded
the number of updates the Perceptron might make on a given training set. It
can be shown (see Exercise 2) that the upper bound is exactly (p/7)?, where p
is the radius of examples and ¥ is the margin.

Soft-SVM and Norm Regularization

The Hard-SVM formulation assumes that the training set is linearly separable,
which is a rather strong assumption. Soft-SVM can be viewed as a relaxation of
the Hard-SVM rule that can be applied even if the training set is not linearly
separable.

The optimization problem in Equation (15.2) enforces the hard constraints
yi((w,x;) +6) > 1 for all i. A natural relaxation is to allow the constraint to be
violated for some of the examples in the training set. This can be modeled by
introducing nonnegative slack variables, £,...,&m, and replacing each constraint
yi((w, x;) +b) > 1 by the constraint y;((w, x;) +6) > 1—€;. That is, €; measures
by how much the constraint y;((w, x;)+b) > 1 is being violated. Soft-SVM jointly
minimizes the norm of w (corresponding to the margin) and the average of &;
(corresponding to the violations of the constraints). The tradeoff between the two

15.2 Soft-SVM and Norm Regularization 207

terms is controlled by a parameter A. This leads to the Soft-SVM optimization

problem:

Soft-SVM
input: (x1, 41),---, (Xm, Ym)
parameter: \ > 0
solve:

an
2, 1m,
wig (aio +2¥«) (15.4)

s.t. Vi, yi((w, xi) +6) >1—€ and & >0

output: w,b

We can rewrite Equation (15.4) as a regularized loss minimization problem.
Recall the definition of the hinge loss:

chinge((w,b), (x, y)) = max{0,1— y((w,x) +b)}.

Given (w,b) and a training set S, the averaged hinge loss on S is denoted by
LRM (Cw, b)). Now, consider the regularized loss minimization problem:

min (llwi? + 23"8°((w,0))) . (15.5)
w,b
CLAIM 15.5 Equation (15.4) and Equation (15.5) are equivalent.

Proof Fix some w,b and consider the minimization over € in Equation (15.4).
Fix some i. Since €; must be nonnegative, the best assignment to €; would be 0
if y;((w, x;) +b) > 1 and would be 1 — y;((w,x;) +b) otherwise. In other words,
&; = Ch8e((w, b), (xi, y:)) for all i, and the claim follows.

We therefore see that Soft-SVM falls into the paradigm of regularized loss
minimization that we studied in the previous chapter. A Soft-SVM algorithm,
that is, a solution for Equation (15.5), has a bias toward low norm separators.
The objective function that we aim to minimize in Equation (15.5) penalizes not
only for training errors but also for large norm.

It is often more convenient to consider Soft-SVM for learning a homogenous
halfspace, where the bias term b is set to be zero, which yields the following
optimization problem:

min (lw? + Ly"**(w)) . (15.6)
w

where

m

inge 1
LI™®°(w) = mn > max{0, 1 — y(w, x;)}.

208

15.2.1

15.2.2

Support Vector Machines

The Sample Complexity of Soft-SVM

We now analyze the sample complexity of Soft-SVM for the case of homogenous
halfspaces (namely, the output of Equation (15.6)). In Corollary 13.8 we derived
a generalization bound for the regularized loss minimization framework assuming
hat the loss function is convex and Lipschitz. We have already shown that the
hinge loss is convex so it is only left to analyze the Lipschitzness of the hinge
oss.

CLAIM 15.6 Let f(w) = max{0,1—y(w,x)}. Then, f is ||x||-Lipschitz.

Proof It is easy to verify that any subgradient of f at w is of the form ax where

a| < 1. The claim now follows from Lemma 14.7.

Corollary 13.8 therefore yields the following:

COROLLARY 15.7 Let D be a distribution over © x {0,1}, where X = {x :
|x|| < p}. Consider running Soft-SVM (Equation (15.6)) on a training set S ~
D™ and let A(S) be the solution of Soft-SVM. Then, for every u,

2p?
Am

Furthermore, since the hinge loss upper bounds the 0—1 loss we also have

lL (A(S))] << LB (u) + All? +

. 2
BE [L9-4(A(S))] < LE8*(a) + All? + 2,

SnD Am
Last, for every B > 0, if we set X= oe then
E (E5*(A(S))) < EB [EB (A(S))] < min _ him (w) +f 828”,
Sapme P ~ sapmi"P = w:|lwii<B > m

We therefore see that we can control the sample complexity of learning a half-

space as a function of the norm of that halfspace, independently of the Euclidean
dimension of the space over which the halfspace is defined. This becomes highly
significant when we learn via embeddings into high dimensional feature spaces,
as we will consider in the next chapter.
Remark 15.2 The condition that 4 will contain vectors with a bounded norm
follows from the requirement that the loss function will be Lipschitz. This is
not just a technicality. As we discussed before, separation with large margin
is meaningless without imposing a restriction on the scale of the instances. In-
deed, without a constraint on the scale, we can always enlarge the margin by
multiplying all instances by a large scalar.

Margin and Norm-Based Bounds versus Dimension

The bounds we have derived for Hard-SVM and Soft-SVM do not depend on the
dimension of the instance space. Instead, the bounds depend on the norm of the

15.2.3

15.2 Soft-SVM and Norm Regularization 209

examples, p, the norm of the halfspace B (or equivalently the margin parameter
y) and, in the nonseparable case, the bounds also depend on the minimum hinge
loss of all halfspaces of norm < B. In contrast, the VC-dimension of the class of
homogenous halfspaces is d, which implies that the error of an ERM hypothesis
decreases as ,\/d/m does. We now give an example in which p?B? < d; hence
the bound given in Corollary 15.7 is much better than the VC bound.

Consider the problem of learning to classify a short text document according
to its topic, say, whether the document is about sports or not. We first need to
represent documents as vectors. One simple yet effective way is to use a bag-

of-words representation. That is, we define a dictionary of words and set the
dimension d to be the number of words in the dictionary. Given a document,
we represent it as a vector x € {0,1}¢, where x; = 1 if the i’th word in the
dictionary appears in the document and x; = 0 otherwise. Therefore, for this
problem, the value of p? will be the maximal number of distinct words in a given
document.

A halfspace for this problem assigns weights to words. It is natural to assume
hat by assigning positive and negative weights to a few dozen words we will
be able to determine whether a given document is about sports or not with
reasonable accuracy. Therefore, for this problem, the value of B? can be set to
be less than 100. Overall, it is reasonable to say that the value of B?p? is smaller
han 10,000.

On the other hand, a typical size of a dictionary is much larger than 10,000.

For example, there are more than 100,000 distinct words in English. We have
herefore shown a problem in which there can be an order of magnitude difference
between learning a halfspace with the SVM rule and learning a halfspace using
he vanilla ERM rule.

Of course, it is possible to construct problems in which the SVM bound will
be worse than the VC bound. When we use SVM, we in fact introduce another
form of inductive bias — we prefer large margin halfspaces. While this induc-

ive bias can significantly decrease our estimation error, it can also enlarge the
approximation error.

The Ramp Loss*

The margin-based bounds we have derived in Corollary 15.7 rely on the fact that
we minimize the hinge loss. As we have shown in the previous subsection, the
term \/p?B?/m can be much smaller than the corresponding term in the VC
bound, \/d/m. However, the approximation error in Corollary 15.7 is measured
with respect to the hinge loss while the approximation error in VC bounds is
measured with respect to the 0—1 loss. Since the hinge loss upper bounds the
0-1 loss, the approximation error with respect to the 0—1 loss will never exceed
that of the hinge loss.

It is not possible to derive bounds that involve the estimation error term
\/pB?/m for the 0-1 loss. This follows from the fact that the 0—1 loss is scale


210

15.3

Support Vector Machines

insensitive, and therefore there is no meaning to the norm of w or its margin
when we measure error with the 0—1 loss. However, it is possible to define a loss
function that on one hand it is scale sensitive and thus enjoys the estimation
error \/p2B?/m while on the other hand it is more similar to the 0-1 loss. One
option is the ramp loss, defined as

e™P (w, (x, y)) = min{1, 28° (w, (x, y))} = min{1, max{0, 1 — y(w,x)}}.

The ramp loss penalizes mistakes in the same way as the 0—1 loss and does not
penalize examples that are separated with margin. The difference between the
ramp loss and the 0—1 loss is only with respect to examples that are correctly
classified but not with a significant margin. Generalization bounds for the ramp
loss are given in the advanced part of this book (see Appendix 26.3).

+
hinge |%»

|, gramp *,

“hese pees

y(w, x)

The reason SVM relies on the hinge loss and not on the ramp loss is that

the hinge loss is convex and, therefore, from the computational point of view,

minimizing the hinge loss can be performed efficiently. In contrast, the problem

of minimizing the ramp loss is computationally intractable.

Optimality Conditions and “Support Vectors” *

The name “Support Vector Machine” stems from the fact that the solution of
hard-SVM, wo, is supported by (i.e., is in the linear span of) the examples that
are exactly at distance 1/||wo|| from the separating hyperplane. These vectors are
therefore called support vectors. To see this, we rely on Fritz John optimality
conditions.

THEOREM 15.8 Let wo be as defined in Equation (15.3) and let I = {i :

|(wo,xi)| = 1}. Then, there exist coefficients a1,...,Qm such that
Wo = Ss OG X;.
wel

The examples {x; : i € I} are called support vectors.
The proof of this theorem follows by applying the following lemma to Equa-
tion (15.3).

15.4

15.4 Duality* 211

LEMMA 15.9 (Fritz John) Suppose that

w* €argmin f(w) s.t. Vi €[m], gi(w) <0,

w

where f,91,---.9m are differentiable. Then, there exists a € R™ such that
Vi (w*) + Vie, iV gi(w*) = 0, where I = {i : gi(w*) = 0}.

Duality*

Historically, many of the properties of SVM have been obtained by considering
the dual of Equation (15.3). Our presentation of SVM does not rely on duality.
For completeness, we present in the following how to derive the dual of Equa-
tion (15.3).

We start by rewriting the problem in an equivalent form as follows. Consider
the function

w a i(w,X;)) =
gw) = acer”: ms Dal (1 = yilw,xi)) co otherwise

io if Vi, y;(w,x;) >1

We can therefore rewrite Equation (15.3) as
min (||w||? + g(w)) . (15.7)
w

Rearranging the preceding we obtain that Equation (15.3) can be rewritten as
the problem

min max (iwi? +o ai( (1— yi(w, «)) . (15.8)

w acR™:a>0
= i=l

Now suppose that we flip the order of min and max in the above equation. This
can only decrease the objective value (see Exercise 4), and we have

7] 2 2 —

i=l

m
> max min les + So ai( (1 — yi (w, wen) .

acR™:a>0
i=l

The preceding inequality is called weak duality. It turns out that in our case,
strong duality also holds; namely, the inequality holds with equality. Therefore,
the dual problem is

acR™:a>0 Ww
~ i=l

max min (Jimi? +o ail (1 — yi(w, =) . (15.9)

We can simplify the dual problem by noting that once a is fixed, the optimization

212

15.5

Support Vector Machines

problem with respect to w is unconstrained and the objective is differentiable;
thus, at the optimum, the gradient equals zero:

m m

w-) ayx = 0 => w=) OUYiXi-
i=1 i=1

This shows us that the solution must be in the linear span of the examples, a
fact we will use later to derive SVM with kernels. Plugging the preceding into
Equation (15.9) we obtain that the dual problem can be rewritten as

2 m
+ oa: fly (Sons) . (15.10)
i=1 i

Rearranging yields the dual problem

1
max z=
acR™:a>0 | 2

m
y OOGYiXt
i=l

mm

in
1
aso ue = 5 Dd aiajyiys (xj-%) | - (15.11)
a

i=1 j=l

Note that the dual problem only involves inner products between instances and
does not require direct access to specific elements within an instance. This prop-
erty is important when implementing SVM with kernels, as we will discuss in
the next chapter.

Implementing Soft-SVM Using SGD

In this section we describe a very simple algorithm for solving the optimization
problem of Soft-SVM, namely,

min (jive + mo max{0, 1 — vw) (15.12)

We rely on the SGD framework for solving regularized loss minimization prob-
lems, as described in Section 14.5.3.
Recall that, on the basis of Equation (14.15), we can rewrite the update rule

of SGD as

1 t
(41)
w xt

where v; is a subgradient of the loss function at w) on the random example
chosen at iteration j. For the hinge loss, given an example (x, y), we can choose v;
to be 0 if y(w),x) > 1 and v; = —yx otherwise (see Example 14.2). Denoting
0) = Viet vj; we obtain the following procedure.

15.6

15.7

15.6 Summary 213

parameter: T
initialize: 0) = 0
pee DT

1 p(t
Let w) = 0! )

If (yi(w,x;) < 1)

Else
Set BOTY = 9

SGD for Solving Soft-SVM

goal: Solve Equation (15.12)

Choose i uniformly at random from [m]

Set BY = OO + yx;

output: w = + vw

Summary

SVM is an algorithm for learning halfspaces with a certain type of prior knowl-

edge, namely, preference for large margin. Hard-SVM seeks the halfspace that

separates the data perfectly with the largest margin, whereas soft-SVM does

not assume separability of the data and allows the constraints to be violated to

some extent. The sample complexity
sample complexity of straightforwar
on the dimension of the domain but
norms of x and w.

The importance of dimension-inde
in the next chapter, where we will
into some high dimensional feature s

or both types of SVM is different from the
halfspace learning, as it does not depend
rather on parameters such as the maximal

pendent sample complexity will be realized
iscuss the embedding of the given domain

ace as means for enriching our hypothesis

class. Such a procedure raises computational and sample complexity problems.

The latter is solved by using SVM, whereas the former can be solved by using

SVM with kernels, as we will see in

Bibliographic Remarks

he next chapter.

SVMs have been introduced in (Cortes & Vapnik 1995, Boser, Guyon & Vapnik
1992). There are many good books on the theoretical and practical aspects of
SVMs. For example, (Vapnik 1995, Cristianini & Shawe-Taylor 2000, Schélkopf
& Smola 2002, Hsu, Chang & Lin 2003, Steinwart & Christmann 2008). Using
SGD for solving soft-SVM has been proposed in Shalev-Shwartz et al. (2007).

214

15.8

Support Vector Machines

Exercises

1. Show that the hard-SVM rule, namely,

argmax min |(w,x;)+)| s.t. Vi, y;((w,x;:) +6) > 0,
(w,b):|[w{]=1  7€[m]

is equivalent to the following formulation:

argmax min y;((w,x;) + 6). (15.13)
(w,b):||wl|=1 tl]

Hint: Define G = {(w, b) : Vi, yi((w, xi) + 6) > O}.
1. Show that

argmax min y;((w,x;) +b) eG
(w,b):|]wl]=1 @€l7]

2. Show that V(w, b) € G,

min y;((w,x;) +b) = min |(w,x;) +d]

ie[m] i€[m]

. Margin and the Perceptron Consider a training set that is linearly sep-

arable with a margin y and such that all the instances are within a ball of
radius p. Prove that the maximal number of updates the Batch Perceptron
algorithm given in Section 9.1.2 will make when running on this training set

is (p/7)?.

3. Hard versus soft SVM: Prove or refute the following claim:

There exists \ > 0 such that for every sample S of m > 1 examples, which
is separable by the class of homogenous halfspaces, the hard-SVM and the
soft-SVM (with parameter X) learning rules return exactly the same weight
vector.

. Weak duality: Prove that for any function f of two vector variables x €

X,y © Y, it holds that

min max f(x,y) > max min f(x, y).
xEX yey Flx,y) 2 yey min f( y)

16

16.1

Kernel Methods

In the previous chapter we described the SVM paradigm for learning halfspaces
in high dimensional feature spaces. This enables us to enrich the expressive
power of halfspaces by first mapping the data into a high dimensional feature
space, and then learning a linear predictor in that space. This is similar to the
AdaBoost algorithm, which learns a composition of a halfspace over base hy-
potheses. While this approach greatly extends the expressiveness of halfspace
predictors, it raises both sample complexity and computational complexity chal-
lenges. In the previous chapter we tackled the sample complexity issue using

he concept of margin. In this chapter we tackle the computational complexity
challenge using the method of kernels.

We start the chapter by describing the idea of embedding the data into a high
dimensional feature space. We then introduce the idea of kernels. A kernel is a
ype of a similarity measure between instances. The special property of kernel

similarities is that they can be viewed as inner products in some Hilbert space
(or Euclidean space of some high dimension) to which the instance space is vir-
ually embedded. We introduce the “kernel trick” that enables computationally
efficient implementation of learning, without explicitly handling the high dimen-

sional representation of the domain instances. Kernel based learning algorithms,

and in particular kernel-SVM, are very useful and popular machine learning

ools. Their success may be attributed both to being flexible for accommodating
domain specific prior knowledge and to having a well developed set of efficient
implementation algorithms.

Embeddings into Feature Spaces

The expressive power of halfspaces is rather restricted — for example, the follow-
ing training set is not separable by a halfspace.
Let the domain be the real line; consider the domain points {—10, —9, —8 ;
1,...,9, 10} where the labels are +1 for all 2 such that |x| > 2 and —1 otherwise.
To make the class of halfspaces more expressive, we can first map the original
instance space into another space (possibly of a higher dimension) and then
learn a halfspace in that space. For example, consider the example mentioned

previously. Instead of learning a halfspace in the original representation let us

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

216

Kernel Methods

first define a mapping 7 : R > R? as follows:
v(e) = («,2°),

We use the term feature space to denote the range of 7. After applying 7 the
data can be easily explained using the halfspace h(x) = sign((w, w(x)) — b),
where w = (0,1) and b= 5.

The basic paradigm is as follows:

1. Given some domain set ¥ and a learning task, choose a mapping q : XY > F,
for some feature space F, that will usually be R" for some n (however, the
range of such a mapping can be any Hilbert space, including such spaces of
infinite dimension, as we will show later).

2. Given a sequence of labeled examples, S = (x1, y1),---,(Xm,Ym), create the
image sequence $ = (1(x1), yids =; (U(Xm), Ym)-

3. Train a linear predictor h over S.

4. Predict the label of a test point, x, to be h((x)).

Note that, for every probability distribution D over XY x Y, we can readily
define its image probability distribution DY over F x Y by setting, for every
subset A C F x Y, DY(A) = D(u~1(A)).! It follows that for every predictor h
over the feature space, Lpu(h) = Lp(how), where hoz is the composition of h
onto wy.

The success of this learning paradigm depends on choosing a good w for a
given learning task: that is, a w that will make the image of the data distribution
(close to being) linearly separable in the feature space, thus making the resulting
algorithm a good learner for a given task. Picking such an embedding requires

prior knowledge about that task. However, often some generic mappings that

enable us to enrich the class of halfspaces and extend its expressiveness are used.

One notable example is polynomial mappings, which are a generalization of the

w we have seen in the previous example.

Recall that the prediction of a standard halfspace classifier on an instance x
is based on the linear mapping x +> (w,x). We can generalize linear mappings
to a polynomial mapping, x ++ p(x), where p is a multivariate polynomial of

degree k. For simplicity, consider first the case in which x is 1 dimensional.
Re+1

In that case, p(x) = an w;x!, where w € is the vector of coefficients
of the polynomial we need to learn. We can rewrite p(x) = (w,%(x)) where
w:R — R**! is the mapping ¢ +> (1, 2, 27, 2°,...,2"). It follows that

learning a k degree polynomial over R can be done by learning a linear mapping

in the (k + 1) dimensional feature space.
More generally, a degree k multivariate polynomial from R” to R can be writ-
ten as

ry. (16.1)

p(x) = Ss wy

Je(n|rir<k é

r

1 This is defined for every A such that ~~1!(A) is measurable with respect to D.

16.2

16.2 The Kernel Trick 217

As before, we can rewrite p(x) = (w,u(x)) where now ~ : R” > R®@ is such
that for every J € [n]"
monomial []}_; x;-

, 1 <k, the coordinate of w(x) associated with J is the

Naturally, polynomial-based classifiers yield much richer hypothesis classes
than halfspaces. We have seen at the beginning of this chapter an example in
which the training set, in its original domain (1 = R), cannot be separable
by a halfspace, but after the embedding x + (x, x”) it is perfectly separable.
So, while the classifier is always linear in the feature space, it can have highly
nonlinear behavior on the original space from which instances were sampled.

In general, we can choose any feature mapping w that maps the original in-

stances into some Hilbert space.2 The Euclidean space R¢ is a Hilbert space for

any finite d. But there are also infinite dimensional Hilbert spaces (as we shall
see later on in this chapter).
The bottom line of this discussion is that we can enrich the class of halfspaces

by first applying a nonlinear mapping, 7), that maps the instance space into some
feature space, and then learning a halfspace in that feature space. However, if
he range of w is a high dimensional space we face two problems. First, the VC-
dimension of halfspaces in R" is n + 1, and therefore, if the range of ¢) is very
arge, we need many more samples in order to learn a halfspace in the range
of w. Second, from the computational point of view, performing calculations in
he high dimensional space might be too costly. In fact, even the representation
of the vector w in the feature space can be unrealistic. The first issue can be

ackled using the paradigm of large margin (or low norm predictors), as we

already discussed in the previous chapter in the context of the SVM algorithm.

In the following section we address the computational issue.

The Kernel Trick

We have seen that embedding the input space into some high dimensional feature
space makes halfspace learning more expressive. However, the computational
complexity of such learning may still pose a serious hurdle — computing linear
separators over very high dimensional data may be computationally expensive.
The common solution to this concern is kernel based learning. The term “kernels”
is used in this context to describe inner products in the feature space. Given
an embedding 7 of some domain space Y into some Hilbert space, we define
the kernel function K(x,x’) = (¢(x),~(x’)). One can think of K as specifying
similarity between instances and of the embedding w as mapping the domain set
2 A Hilbert space is a vector space with an inner product, which is also complete. A space is
complete if all Cauchy sequences in the space converge.
In our case, the norm ||w]|] is defined by the inner product \/(w,w). The reason we require
the range of w to be in a Hilbert space is that projections in a Hilbert space are well
defined. In particular, if M is a linear subspace of a Hilbert space, then every x in the

Hilbert space can be written as a sum x = u+ v where u € M and (v,w) = 0 for all
w € M. We use this fact in the proof of the representer theorem given in the next section.

218

Kernel Methods

&X into a space where these similarities are realized as inner products. It turns
out that many learning algorithms for halfspaces can be carried out just on the
basis of the values of the kernel function over pairs of domain points. The main
advantage of such algorithms is that they implement linear separators in high
dimensional feature spaces without having to specify points in that space or
expressing the embedding w explicitly. The remainder of this section is devoted
o constructing such algorithms.

In the previous chapter we saw that regularizing the norm of w yields a small
sample complexity even if the dimensionality of the feature space is high. Inter-
estingly, as we show later, regularizing the norm of w is also helpful in overcoming
he computational problem. To do so, first note that all versions of the SVM op-
imization problem we have derived in the previous chapter are instances of the

‘ollowing general problem:
main (f ((w,w(2e1)) +--+. QW, W(m))) + Rl) (16.2)

where f : R” — R is an arbitrary function and R : R, —> R is a monotoni-
cally nondecreasing function. For example, Soft-SVM for homogenous halfspaces
(Equation (15.6)) can be derived from Equation (16.2) by letting R(a) = Aa? and
f(ai,---, Gm) = a >>; max{0, 1—y;a;}. Similarly, Hard-SVM for nonhomogenous
halfspaces (Equation (15.2)) can be derived from Equation (16.2) by letting
R(a) = a’ and letting f(a1,...,am) be 0 if there exists b such that y;(a;+b) > 1

for all i, and f(a1,...,dm) = 00 otherwise.

The following theorem shows that there exists an optimal solution of Equa-
tion (16.2) that lies in the span of {7(x1),...,v(%m)}-
THEOREM 16.1 (Representer Theorem) Assume that w is a mapping from X to
m

a Hilbert space. Then, there exists a vector a € R™ such that w = S7¥", ajt)(xi)
is an optimal solution of Equation (16.2).

Proof Let w* be an optimal solution of Equation (16.2). Because w* is an
element of a Hilbert space, we can rewrite w* as

m

w= Ss ajtb(xi) + u,
i=1

where (u, 7)(x;)) = 0 for all i. Set w = w* — u. Clearly, ||w*||? = ||w||? + |Jull?,
hus ||w|| < ||w*||. Since R is nondecreasing we obtain that R(||w||) < R(||w*||).
Additionally, for all i we have that

(ww (oc:)) = (wt — a, (i) = (Ww, (0),

nence

We have shown that the objective of Equation (16.2) at w cannot be larger

han the objective at w* and therefore w is also an optimal solution. Since

w= dio

iw(x;) we conclude our proof.


16.2 The Kernel Trick 219

On the basis of the representer theorem we can optimize Equation (16.2) with
respect to the coefficients a instead of the coefficients w as follows. Writing
w= 5, aj(x;) we have that for all i

m

(w, w(x:)) -(r ajh(x;), W(x: =} desl x;), (x).

Similarly,

m

\IwlP = (x ess). a,v)) = YE ai; (h(x), ¥Oc)))-
j j

ij=l

Let K(x,x’) = (#(x), &(x’)) be a function that implements the kernel function
with respect to the embedding 7). Instead of solving Equation (16.2) we can solve
the equivalent problem

min, f Leak, X1),- aK G,Xm)

acR™

(16.3)

To solve the optimization problem given in Equation (16.3), we do not need any
direct access to elements in the feature space. The only thing we should know is
how to calculate inner products in the feature space, or equivalently, to calculate
the kernel function. In fact, to solve Equation (16.3) we solely need to know the
value of the m x m matrix G s.t. Gi; = K(x;:,x,;), which is often called the
Gram matrix.

In particular, specifying the preceding to the Soft-SVM problem given in Equa-
tion (15.6), we can rewrite the problem as

: T i< ; .
amin, (> Ga+ mn > max {0,1 — (Ga) ; (16.4)
where (Ga); is the i’th element of the vector obtained by multiplying the Gram
matrix G by the vector a. Note that Equation (16.4) can be written as quadratic
programming and hence can be solved efficiently. In the next section we describe
an even simpler algorithm for solving Soft-SVM with kernels.

Once we learn the coefficients a we can calculate the prediction on a new
instance by

m m

= w(x;), = ak bo.%) x

The advantage of working with kernels rather than directly optimizing w in
the feature space is that in some situations the dimension of the feature space

220

Kernel Methods

is extremely large while implementing the kernel function is very simple. A few
examples are given in the following.

Example 16.1 (Polynomial Kernels) The k degree polynomial kernel is defined
to be

K(x,x’) = (1+ (x,x’))*.

Now we will show that this is indeed a kernel function. That is, we will show
that there exists a mapping ~ from the original space to some higher dimensional
space for which K(x,x’) = (w(x), 7(x’)). For simplicity, denote zo = xj = 1.
Then, we have

K(x,x') = (1 + (x,x’))* = (1+ (x,x’))----- (1+ (x,x’))
= SO 252%, sees SO x52
j=0 j=0
k

> Il LyX'y,

JE{O,1,...,n}* i= 1
k .

JE{OA,.npeisl i=l

Now, if we define 7 : R” > R@+D" such that for J € {0, 1,...,n}* there is an
ement of o(x) that equals []*_, xy,, we obtain that

K(x, x’) = (a(x), o(x’)).

©

Since 7 contains all the monomials up to degree k, a halfspace over the range
of w corresponds to a polynomial predictor of degree k over the original space.
Hence, learning a halfspace with a k degree polynomial kernel enables us to learn
polynomial predictors of degree k over the original space.

Note that here the complexity of implementing K is O(n) while the dimension

of the feature space is on the order of n*.

Example 16.2 (Gaussian Kernel) Let the original instance space be R and
consider the mapping y where for each nonnegative integer n > 0 there exists
ae

«
an element w(a),, that equals —L eZ x". Then,

Val

(wo). wer = Do (ea) (Ge ® eo")

n=0

a e')? SS / (ra!)”
EEN)

n=0

Il2—2' |?
=e 2

Here the feature space is of infinite dimension while evaluating the kernel is very

16.2.1

16.2 The Kernel Trick 221

simple. More generally, given a scalar o > 0, the Gaussian kernel is defined to
be

_ eax"?

K(x,x')=e 2¢

Intuitively, the Gaussian kernel sets the inner product in the feature space
between x,x’ to be close to zero if the instances are far away from each other
(in the original domain) and close to 1 if they are close. o is a parameter that
controls the scale determining what we mean by “close.” It is easy to verify that
4 implements an inner product in a space in which for any n and any monomial
Il>elh

2

1

of order k there exists an element of (x) that equals ~=e~ ”

ia VI:

Hence, we can learn any polynomial predictor over the original space by using a
Gaussian kernel.

Recall that the VC-dimension of the class of all polynomial predictors is infi-
nite (see Exercise 12). There is no contradiction, because the sample complexity
required to learn with Gaussian kernels depends on the margin in the feature
space, which will be large if we are lucky, but can in general be arbitrarily small.

The Gaussian kernel is also called the RBF kernel, for “Radial Basis Func-
tions.”

Kernels as a Way to Express Prior Knowledge

As we discussed previously, a feature mapping, ~, may be viewed as expanding
the class of linear classifiers to a richer class (corresponding to linear classifiers
over the feature space). However, as discussed in the book so far, the suitability
of any hypothesis class to a given learning task depends on the nature of that
task. One can therefore think of an embedding w as a way to express and utilize
prior knowledge about the problem at hand. For example, if we believe that
positive examples can be distinguished by some ellipse, we can define y to be all
the monomials up to order 2, or use a degree 2 polynomial kernel.

As a more realistic example, consider the task of learning to find a sequence of
characters (“signature”) in a file that indicates whether it contains a virus or not.

Formally, let Xq be the set of all strings of length at most d over some alphabet
set =. The hypothesis class that one wishes to learn is H = {hy : v € Xa}, where,

for a string « € Vg, hy (2) is 1 iff v is a substring of x (and h,(x) = —1 otherwise).
Let us show how using an appropriate embedding this class can be realized by
linear classifiers over the resulting feature space. Consider a mapping y to a space
R* where s = |Xq|, so that each coordinate of (x) corresponds to some string v
and indicates whether v is a substring of x (that is, for every x € Yq, 7(x) is a
vector in {0, 1}!*4!), Note that the dimension of this feature space is exponential

in d. It is not hard to see that every member of the class H can be realized by

composing a linear classifier over 7(a), and, moreover, by such a halfspace whose
norm is 1 and that attains a margin of 1 (see Exercise 1). Furthermore, for every

x € &, |\¥(x)|| = O(d). So, overall, it is learnable using SVM with a sample

222

16.2.2

16.3

Kernel Methods

complexity that is polynomial in d. However, the dimension of the feature space
is exponential in d so a direct implementation of SVM over the feature space is
problematic. Luckily, it is easy to calculate the inner product in the feature space
(i.e., the kernel function) without explicitly mapping instances into the feature
space. Indeed, K’(
which can be easily calculated in time polynomial in d.

x,x’) is simply the number of common substrings of x and 2’,

This example also demonstrates how feature mapping enables us to use halfspaces
for nonvectorial domains.

Characterizing Kernel Functions*

As we have discussed in the previous section, we can think of the specification of
the kernel matrix as a way to express prior knowledge. Consider a given similarity
function of the form K : ¥ x ¥ > R. Is it a valid kernel function? That is, does
it represent an inner product between (x) and 7(x’) for some feature mapping
w? The following lemma gives a sufficient and necessary condition.

LEMMA 16.2 A symmetric function K : ¥ x X — R implements an inner
product in some Hilbert space if and only if it is positive semidefinite; namely,
for all xi,..., Xm, the Gram matrix, Gi; = K(x;,x;), is a positive semidefinite

matriz.

Proof It is trivial to see that if K implements an inner product in some Hilbert
space then the Gram matrix is positive semidefinite. For the other direction,
define the space of functions over ¥ as R* = {f : X — R}. For each x € Vv
let (x) be the function x +> K(-,x). Define a vector space by taking all linear
combinations of elements of the form K(-,x). Define an inner product on this
vector space to be

(x cars SKC.) = So a8) K (xi, x4).
i j ij

This is a valid inner product since it is symmetric (because K is symmetric), it is
linear (immediate), and it is positive definite (it is easy to see that K(x,x) > 0
with equality only for ~(x) being the zero function). Clearly,

(W(x), We) = (K(x), K(x) = Kx"),

which concludes our proof.

Implementing Soft-SVM with Kernels

Next, we turn to solving Soft-SVM with kernels. While we could have designed
an algorithm for solving Equation (16.4), there is an even simpler approach that

16.3 Implementing Soft-SVM with Kernels 223

directly tackles the Soft-SVM optimization problem in the feature space,

m
min (Ziv + mma.) = lH) ; (16.5)
while only using kernel evaluations. The basic observation is that the vector w
maintained by the SGD procedure we have described in Section 15.5 is always in
the linear span of {1b(x1),...,7(Xm)}- Therefore, rather than maintaining w
we can maintain the corresponding coefficients a.

Formally, let K be the kernel function, namely, for all x,x’, K(x,x’) =
(w(x), Y(x’)). We shall maintain two vectors in R™, corresponding to two vectors
a and w) defined in the SGD procedure of Section 15.5. That is, 8 will be
a vector such thai

m
0 =S~ BM w(x;) (16.6)
j=l
and a) be such that
m
w = Ss al a(x). (16.7)
j=l

The vectors 3 and @ are updated according to the following procedure.

SGD for Solving Soft-SVM with Kernels

Goal: Solve Equation (16.5)
parameter: T
Initialize: 8) =0
fort=1,...,T
Let a = tp
Choose i uniformly at random from [m]
For all j Zi set Bt) = pO
Tf vi Dy YK (xj, x1) < 1)
Set BOTY = BO +4. y,
Else
Set pltD = pO
Output: w = 7", ajy(x;) where @ = yea

The following lemma shows that the preceding implementation is equivalent
to running the SGD procedure described in Section 15.5 on the feature space.

LEMMA 16.3 Let w be the output of the SGD procedure described in Sec-
tion 15.5, when applied on the feature space, and let Ww = vy ajw(x;) be
the output of applying SGD with kernels. Then w = w.

Proof We will show that for every t Equation (16.6) holds, where 0 is the
result of running the SGD procedure described in Section 15.5 in the feature

224

16.4

Kernel Methods

space. By the definition of a = $8 and w(!) = 0, this claim implies
that Equation (16.7) also holds, and the proof of our lemma will follow. To prove
that Equation (16.6) holds we use a simple inductive argument. For t = 1 the
claim trivially holds. Assume it holds for t > 1. Then,

m

Yi (w, vOxi)) =i (x al ab(x;), i) =i > al K(x), xi).

j=l
Hence, the condition in the two algorithms is equivalent and if we update @ we
have

m m

OD = AO + yh) = S° BOYER) + yl) = > BI YP WER)),
j=l j=l

which concludes our proof.

Summary

Mappings from the given domain to some higher dimensional space, on which a
halfspace predictor is used, can be highly powerful. We benefit from a rich and
complex hypothesis class, yet need to solve the problems of high sample and
computational complexities. In Chapter 10, we discussed the AdaBoost algo-
rithm, which faces these challenges by using a weak learner: Even though we’re

“oracle” that bestows on us a

in a very high dimensional space, we have an
single good coordinate to work with on each iteration. In this chapter we intro-
duced a different approach, the kernel trick. The idea is that in order to find a
halfspace predictor in the high dimensional space, we do not need to know the

representation of instances in that space, but rather the values of inner products

between the mapped instances. Calculating inner products between instances in
the high dimensional space without using their representation in that space is
done using kernel functions. We have also shown how the SGD algorithm can be
implemented using kernels.

The ideas of feature mapping and the kernel trick allow us to use the framework
of halfspaces and linear predictors for nonvectorial data. We demonstrated how
kernels can be used to learn predictors over the domain of strings.

We presented the applicability of the kernel trick in SVM. However, the kernel
trick can be applied in many other algorithms. A few examples are given as
exercises.

This chapter ends the series of chapters on linear predictors and convex prob-
lems. The next two chapters deal with completely different types of hypothesis
classes.

16.5

16.6

16.5 Bibliographic Remarks 225

Bibliographic Remarks

In the context of SVM, the kernel-trick has been introduced in Boser et al. (1992).
See also Aizerman, Braverman & Rozonoer (1964). The observation that the
kernel-trick can be applied whenever an algorithm only relies on inner products
was first stated by Schélkopf, Smola & Miiller (1998). The proof of the representer
theorem is given in (Schélkopf, Herbrich, Smola & Williamson 2000, Schélkopf,
Herbrich & Smola 2001). The conditions stated in Lemma 16.2 are simplification
of conditions due to Mercer. Many useful kernel functions have been introduced
in the literature for various applications. We refer the reader to Schdlkopf &
Smola (2002).

Exercises

1. Consider the task of finding a sequence of characters in a file, as described
in Section 16.2.1. Show that every member of the class H can be realized by
composing a linear classifier over w(x), whose norm is 1 and that attains a
margin of 1.

2. Kernelized Perceptron: Show how to run the Perceptron algorithm while
only accessing the instances via the kernel function. Hint: The derivation is
similar to the derivation of implementing SGD with kernels.

3. Kernel Ridge Regression: The ridge regression problem, with a feature
mapping 7, is the problem of finding a vector w that minimizes the function

m

; : 1 , .
fw) = Aljwl? + 5 Mw wb(i)) — i)”, (16.8)

and then returning the predictor

h(x)

(w,x).

Show how to implement the ridge regression algorithm with kernels.
Hint: The representer theorem tells us that there exists a vector a € R”

such that >)", aiv(x;) is a minimizer of Equation (16.8).

1. Let G be the Gram matrix with regard to S and K. That is, Gij =
K(x;,x;). Define g : R™ + R by

T Li< 2 ,
g(a) =A-a*Ga+ om da.G) — yi)”, (16.9)

where G.; is the #’th column of G. Show that if a* minimizes Equa-
tion (16.9) then w* = 77", a¥u(x;) is a minimizer of f.

2. Find a closed form expression for a*.

4. Let N be any positive integer. For every x,x’ € {1,..., N} define

K(a,2') = min{z, 2}.

226 Kernel Methods

Prove that K is a valid kernel; namely, find a mapping w: {1,...,N} > H
where H is some Hilbert space, such that

Va,x' € {1,...,N}, K(a,2’) = (W(2), ¥(2’)).

. A supermarket manager would like to learn which of his customers have babies

on the basis of their shopping carts. Specifically, he sampled i.i.d. customers,
where for customer i, let x; C {1,...,d} denote the subset of items the
customer bought, and let y; € {+1} be the label indicating whether this
customer has a baby. As prior knowledge, the manager knows that there are

k items such that the label is determined to be 1 iff the customer bought

at least one of these k items. Of course, the identity of these k items is not
known (otherwise, there was nothing to learn). In addition, according to the

store regulation, each customer can buy at most s items. Help the manager to
design a learning algorithm such that both its time complexity and its sample
complexity are polynomial in s,k, and 1/e.

. Let ¥ be an instance set and let 7 be a feature mapping of ¥ into some

Hilbert feature space V. Let K : ¥% x & > R be a kernel function that
implements inner products in the feature space V.

Consider the binary classification algorithm that predicts the label of
an unseen instance according to the class with the closest average. Formally,

given a training sequence S = (x1,y1),---,(Xm,Ym), for every y € {£1} we
define
1 ;
Cy = Ss (xi).
Y iey=y

where my, = |{i : y; = y}|. We assume that m, and m_ are nonzero. Then,
the algorithm outputs the following decision rule:

_ Jt Webe) — ex ll s Iles) - ell

A(x) =
0 otherwise.

1. Let w = cy —c_ and let b= $((\c_||? — ||c+|]?). Show that
h(x) = sign((w, u(x) +d).

2. Show how to express h(x) on the basis of the kernel function, and without
accessing individual entries of ~(x) or w.

17

17.1

Multiclass, Ranking, and Complex
Prediction Problems

Multiclass categorization is the problem of classifying instances into one of several
possible target classes. That is, we are aiming at learning a predictor h: XY > ),
where Y is a finite set of categories. Applications include, for example, catego-
rizing documents according to topic (4 is the set of documents and Y is the set

°

possible topics) or determining which object appears in a given image (7 is
the set of images and J is the set of possible objects).

The centrality of the multiclass learning problem has spurred the development
of various approaches for tackling the task. Perhaps the most straightforward

approach is a reduction from multiclass classification to binary classification. In
Section 17.1 we discuss the most common two reductions as well as the main
drawback of the reduction approach.

We then turn to describe a family of linear predictors for multiclass problems.
Relying on the RLM and SGD frameworks from previous chapters, we describe
several practical algorithms for multiclass prediction.

In Section 17.3 we show how to use the multiclass machinery for complex pre-
diction problems in which Y can be extremely large but has some structure on
it. This task is often called structured output learning. In particular, we demon-
strate this approach for the task of recognizing handwritten words, in which Y
is the set of all possible strings of some bounded length (hence, the size of ) is

exponential in the maximal length of a word).
Finally, in Section 17.4 and Section 17.5 we discuss ranking problems in which
the learner should order a set of instances according to their “relevance.” A typ-

ical application is ordering results of a search engine according to their relevance
to the query. We describe several performance measures that are adequate for

assessing the performance of ranking predictors and describe how to learn linear

predictors for ranking problems efficiently.

One-versus-All and All-Pairs

The simplest approach to tackle multiclass prediction problems is by reduction

to binary classification. Recall that in multiclass prediction we would like to learn
a function h: ¥ + Y. Without loss of generality let us denote Y = {1,...,k}.
In the One-versus-All method (a.k.a. One-versus-Rest) we train k binary clas-

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

228 Multiclass, Ranking, and Complex Prediction Problems

sifiers, each of which discriminates between one class and the rest of the classes.
That is, given a training set S' = (x1, y1),---,(Xm; Ym), where every y; is in Y, we
construct k binary training sets, $1,...,.S,, where $; = (x1, (—1)'4),..., (Xm, (—1) fm).
In words, $; is the set of instances labeled 1 if their label in S was i, and —1
otherwise. For every i € [k] we train a binary predictor h; : ¥ > {+1} based on
S;, hoping that h;(x) should equal 1 if and only if x belongs to class i. Then,

given h,,...,h,, we construct a multiclass predictor using the rule

h(x) € argmax h;(x). (17.1)
4€[k]

When more than one binary hypothesis predicts “1” we should somehow decide

which class to predict (e.g., we can arbitrarily decide to break ties by taking the
minimal index in argmax;, h;(x)). A better approach can be applied whenever
each h; hides additional information, which can be interpreted as the confidence
in the prediction y = i. For example, this is the case in halfspaces, where the
actual prediction is sign((w, x)), but we can interpret (w, x) as the confidence
in the prediction. In such cases, we can apply the multiclass rule given in Equa-
tion (17.1) on the real valued predictions. A pseudocode of the One-versus-All
approach is given in the following.

One-versus-All

input:

raining set S' = (x1, y1),---, (Xm, Ym)

algorithm for binary classification A

foreach i € Y

let Si = (x1, (—1)"™ 44), ...,(&m, (—1) ema)

let h; = A(S;)

output:

he multiclass hypothesis defined by h(x) € argmax;¢y hi(x)

Another popular reduction is the All-Pairs approach, in which all pairs of
classes are compared to each other. Formally, given a training set S = (x1, y1),.--, (Xm; Ym),
where every y; is in [k], for every 1 < i < j < k we construct a binary training
sequence, $;,;, containing all examples from S$ whose label is either i or j. For
each such an example, we set the binary label in S;,; to be +1 if the multiclass
label in S is i and —1 if the multiclass label in S is j. Next, we train a binary
classification algorithm based on every Sj,; to get hij. Finally, we construct
a multiclass classifier by predicting the class that had the highest number of
“wins.” A pseudocode of the All-Pairs approach is given in the following.


17.1 One-versus-All and All-Pairs

229

All-Pairs

input:
training set S = (x), 41)
algorithm for binary classification A
foreach i,j € Vs.t.i <j

for t=1,...,m
If y =i add (x;,1) to Sj;
If y = j add (x;,—1) to $;,;
let hij = A(Si,;)
output:
the multiclass hypothesis defined by

h(x) € argmax;cy (yey sign(j — i) hi

initialize S;,; to be the empty sequence

(9)

Altho

simple and easy to constr

ugh reduction me
price. The binary learner is not aware of the fact t
output
ustrated in the following
Example 17.1
stance s

the la’
locate:

pace is ¥ = R? an bel set is Y = {1, 2,

of the different classes are in nonintersecting

lowing.

hods such as the One-versus-All and All-Pairs are
uct from existing algorithms, their simplici

y has a
hat we are going to use its
hypotheses for constructing a multiclass pre
to suboptimal results, as i

ictor, and this might lead
example.

Consider a multiclass categorization problem in which the in-

3}. Suppose that instances
alls as depicted in the fol-

one

Suppose that the probability masses of classes 1, 2,

3 are 40%, 20%, and 40%,

respectively. Consider the application of One-versus-All to this problem, and as-

sume that the binary classification algorithm used

by One-versus-All is ERM

with respect to the hypothesis class of halfspaces. Observe that for the prob-

lem of discriminating between class 2 and the rest
halfspace would be the all negative classifier. There
tor constructed by One-versus-All might err on all
(this will be the case if the tie in the definition of
merical value of the class label). In contrast, if we

where wi = (-45:5), w2 = (0,1), and wz

fier defined by h(x) = argmax; h;(x) perfectly predic

of the classes, the optimal
ore, the multiclass predic-
the examples from class 2
h(x) is broken by the nu-
e choose hj(x) = (wi,x),

ot wa ; then the classi-
ts all the examples. We see

230

17.2

17.2.1

Multiclass, Ranking, and Complex Prediction Problems

that even though the approximation error of the class of predictors of the form
h(x) = argmax;(w;,x) is zero, the One-versus-All approach might fail to find a
good predictor from this class.

Linear Multiclass Predictors

In light of the inadequacy of reduction methods, in this section we study a more
direct approach for learning multiclass predictors. We describe the family of
linear multiclass predictors. To motivate the construction of this family, recall
that a linear predictor for binary classification (i.e., a halfspace) takes the form

h(x) = sign((w,x)).
An equivalent way to express the prediction is as follows:

h(x) = argmax (w, yx),
ye{tl}
where yx is the vector obtained by multiplying each element of x by y.

This representation leads to a natural generalization of halfspaces to multiclass
problems as follows. Let UV: ¥ x Y — R¢ be a class-sensitive feature mapping.
That is, Y takes as input a pair (x,y) and maps it into a d dimensional feature
vector. Intuitively, we can think of the elements of (x, y) as score functions that
assess how well the label y fits the instance x. We will elaborate on W later on.
Given W and a vector w € R®, we can define a multiclass predictor, h: ¥ > ),
as follows:

h(x) = argmax (w, U(x, y)).

yey

That is, the prediction of h for the input x is the label that achieves the highest
weighted score, where weighting is according to the vector w.

Let W be some set of vectors in R@, for example, W = {w € R@: ||w|| < B},
for some scalar B > 0. Each pair (Y,W) defines a hypothesis class of multiclass

predictors:
Huw = {x argmax (w, U(x,y)) : we WH.
yey
Of course, the immediate question, which we discuss in the sequel, is how to
construct a good WV. Note that if Y = {+1} and we set U(x,y) = yx and
W = R%, then Hw,w becomes the hypothesis class of homogeneous halfspace

predictors for binary classification.

How to Construct UV

As mentioned before, we can think of the elements of U(x, y) as score functions
that assess how well the label y fits the instance x. Naturally, designing a good UV
is similar to the problem of designing a good feature mapping (as we discussed in

17.2 Linear Multiclass Predictors 231

Chapter 16 and as we will discuss in more detail in Chapter 25). Two examples
of useful constructions are given in the following.

The Multivector Construction:
Let Y = {1,...,k} and let XY = R”. We define VU: ¥ x Yo R®, where d = nk,
as follows

W(x, y) =[ 0,...,0, 21,...,2n, 0,...,0 J. (17.2)
QA ee
ERW—Dn eR” ER(-u)n

That is, U(x, y) is composed of k vectors, each of which is of dimension n, where
we set all the vectors to be the all zeros vector except the y’th vector, which is
set to be x. It follows that we can think of w € R”* as being composed of k
weight vectors in R", that is, w = [wi; ... ; wz], hence the name multivec-
tor construction. By the construction we have that (w, U(x, y)) = (wy,x), and
therefore the multiclass prediction becomes
h(x) = argmax (wy, x).
yey

A geometric illustration of the multiclass prediction over X = R? is given in the
following.

TF-IDF:

The previous definition of U(x, y) does not incorporate any prior knowledge
about the problem. We next describe an example of a feature function W that
does incorporate prior knowledge. Let ¥ be a set of text documents and Y be a
set of possible topics. Let d be a size of a dictionary of words. For each word in the
dictionary, whose corresponding index is j, let TF(j,x) be the number of times
the word corresponding to 7 appears in the document x. This quantity is called
Term-Frequency. Additionally, let DF(j,y) be the number of times the word
corresponding to j appears in documents in our training set that are not about
topic y. This quantity is called Document-Frequency and measures whether word
j is frequent in other topics. Now, define UV : ¥ x Y > R¢ to be such that

U,(x,y) = TPU,x) log (axe):

where m is the total number of documents in our training set. The preced-
ing quantity is called term-frequency-inverse-document-frequency or TF-IDF for

232

17.2.2

17.2.3

Multiclass, Ranking, and Complex Prediction Problems

short. Intuitively, Uj(x, y) should be large if the word corresponding to j ap-
pears a lot in the document x but does not appear at all in documents that are
not on topic y. If this is the case, we tend to believe that the document x is on
topic y. Note that unlike the multivector construction described previously, in
the current construction the dimension of YW does not depend on the number of
topics (i.e., the size of )).

Cost-Sensitive Classification

So far we used the zero-one loss as our performance measure of the quality of
h(x). That is, the loss of a hypothesis h on an example (x, y) is 1 if h(x) A y and
0 otherwise. In some situations it makes more sense to penalize different levels
of loss for different mistakes. For example, in object recognition tasks, it is less
severe to predict that an image of a tiger contains a cat than predicting that
the image contains a whale. This can be modeled by specifying a loss function,
A:YxyY — Ri, where for every pair of labels, y’,y, the loss of predicting
the label y’ when the correct label is y is defined to be A(y’,y). We assume

that A(y, y) = 0. Note that the zero-one loss can be easily modeled by setting
AY, y) = ly zu)-

ERM

We have defined the hypothesis class Hw,w and specified a loss function A. To
learn the class with respect to the loss function, we can apply the ERM rule with
respect to this class. That is, we search for a multiclass hypothesis h € Hw,w,
parameterized by a vector w, that minimizes the empirical risk with respect to
A,
Lg(h) = 1 52 A(h(x:) Yi)
‘ =—_ i)sYi)-
” mia
We now show that when W = R¢ and we are in the realizable case, then it is
possible to solve the ERM problem efficiently using linear programming. Indeed,
in the realizable case, we need to find a vector w € R¢ that satisfies

Vie [m], yy = argmax(w, V(x;,y)).
yey

Equivalently, we need that w will satisfy the following set of linear inequalities
wie [m], Wy EV \ {yi}, (we UC. yi) > Cw, YOu).

Finding w that satisfies the preceding set of linear equations amounts to solving
a linear program.

As in the case of binary classification, it is also possible to use a generalization
of the Perceptron algorithm for solving the ERM problem. See Exercise 2.

In the nonrealizable case, solving the ERM problem is in general computa-
tionally hard. We tackle this difficulty using the method of convex surrogate

17.2.4

17.2 Linear Multiclass Predictors 233

loss functions (see Section 12.3). In particular, we generalize the hinge loss to
multiclass problems.

Generalized Hinge Loss

Recall that in binary classification, the hinge loss is defined to be max{0, 1 —
y(w,x)}. We now generalize the hinge loss to multiclass predictors of the form

hw (x) = argmax (w, U(x, y’)).
yey

Recall that a surrogate convex loss should upper bound the original nonconvex

loss, which in our case is A(hw(x), y). To derive an upper bound on A(hw(x), y)
we first note that the hints “of hw(x) implies that

(w, U(x, y)) < (w, U(x, hw(x))).
Therefore,
A(hw(x),y) < A(hw(x),y) + (w, U(x, hw(x)) — U(x, y)).

Since hy,(x) € Y we can upper bound the right-hand side of the preceding by
def Q

max (A(y',y) + (w,¥(x,y')—¥(x,y))) = ew, (x,y). (17.3)

We use the term ae hinge loss” denote the preceding expression. As

we have shown, ¢(w, (x,y)) > A(hw(x),y). Furthermore, equality holds when-

ever the score of the correct label is larger na the score of any other label, y’,

by at least A(y’, y), namely,
vy EYV\ {uy}, (w, YK. y)) = Cw, U(x, y')) + Ay’ y).

It is also immediate to see that ¢(w, (x, y)) is a convex function with respect to w

since it is a maximum over linear functions of w (see Claim 12.5 in Chapter 12),
and that ¢(w, (x,y)) is p-Lipschitz with p = maxy cy ||V(x, y’) — U(x, y)|l.

Remark 17.2 We use the name “generalized hinge loss” since in the binary

case, when Y = {+1}, if we set U(x,y) = 4, then the generalized hinge loss
becomes the vanilla hinge loss for binary classification,

l(w, (x, y)) = max{0, 1 — y(w,x)}.

Geometric Intuition:

The feature function © : ¥ x Y > R* maps each x into || vectors in R¢.
The value of ¢(w,(x,y)) will be zero if there exists a direction w such that
when projecting the || vectors onto this direction we obtain that each vector is
represented by the scalar (w, U(x, y)), and we can rank the different points on
the basis of these scalars so that

e The point corresponding to the correct y is top-ranked

234

17.2.5

Multiclass, Ranking, and Complex Prediction Problems

e For each y' 4 y, the difference between (w, U(x, y)) and (w, U(x, y’)) is larger

(w, U(x, y’)) is also referred to as the “margin” (see Section 15.1).

This is illustrated in the following figure:

Multiclass SVM and SGD

than the loss of predicting y’ instead of y. The difference (w, U(x, y)) —

Once we have defined the generalized hinge loss, we obtain a convex-Lipschitz

learning problem and we can apply our general techniques for solving such

lems. In particular, the RLM technique we have studied in Chapter 13 yiel
multiclass SVM rule:

Multiclass SVM

input: (x1, y1),---, (Km; Ym)
parameters:

regularization parameter \ > 0

loss function A: Y x Y > Ry

class-sensitive feature mapping U: ¥ x Y > R?
solve:

eR4

ra
in { Aljw|[? + — ax (A(y’, yi U(x, y!) — U(x, yi
amin (aio > max (A(y/.ui) + (Ww, U(xi.y') — Ux)

output the predictor hw(x) = argmax,cy(w, U(x, y))

prob-
s the

We can solve the optimization problem associated with multiclass SVM us-

ing gi

eneric convex optimization algorithms (or using the method described in

Section 15.5). Let us analyze the risk of the resulting hypothesis. The analysis

seam.

essly follows from our general analysis for convex-Lipschitz problems given

in Chapter 13. In particular, applying Corollary 13.8 and using the fact that the

generalized hinge loss upper bounds the A loss, we immediately obtain an analog

of Corollary 15.7:

COROLLARY 17.1

Let D be a distribution over X x ), let U: Xx Y > R4,

and assume that for allx € X andy € Y we have ||U(x, y)|| < p/2. Let B> 0.

17.2 Linear Multiclass Predictors 235

Consider running Multiclass SVM with \ = V 30° on a training set S ~ D™

Bem

and let hy be the output of Multiclass SVM. Then,

[LB (hw)] < &E [LS BPS (w)] < min TS binge (yy 8p? BZ
~ Sebel? ~ ulul<e ? m”

SnoD™

where LB(h) = Eyl A(h(x),y)] and LE" ™°(w) = Ee y~vlé(w, (x,y))]
with £ being the generalized hinge-loss as defined in Equation (17.3).

We can also apply the SGD learning framework for minimizing LEM e*(w) as

described in Chapter 14. Recall Claim 14.6, which dealt with subgradients of max
functions. In light of this claim, in order to find a subgradient of the generalized
hinge loss all we need to do is to find y € Y that achieves the maximum in the
definition of the generalized hinge loss. This yields the following algorithm:

SGD for Multiclass Learning

parameters:
Scalar 7 > 0, integer T > 0
loss function A: Y x Y > Ry
class-sensitive feature mapping U: ¥ x Y > R?
initialize: w) =0 € R¢
fort =1, 2,...,T
sample (x, y) ~ D
find 9 € argmaxy ey (A(y’,y) + (w, U(x, y') — U(x, y)))
set v, = U(x, 9) — U(x, y)
update w+) = w — nv,

output w= + ew

Our general analysis of SGD given in Corollary 14.12 immediately implies:

COROLLARY 17.2 Let D be a distribution over X x Y, let UV: X x Y > R4,
and assume that for allx € X andy € Y we have ||U(x,y)|| < p/2. Let B> 0.
Then, for every € > 0, if we run SGD for multiclass learning with a number of
iterations (i.e., number of examples)

22
> Be

T

e
and with n = Ver then the output of SGD satisfies

E [L8(hw)) < .E [LS >™*°(w)] < min LEM (u) +e.

swDm SwDm u:ljul SB

Remark 17.3 It is interesting to note that the risk bounds given in Corol-
lary 17.1 and Corollary 17.2 do not depend explicitly on the size of the label
set Y, a fact we will rely on in the next section. However, the bounds may de-
pend implicitly on the size of Y via the norm of U(x, y) and the fact that the
bounds are meaningful only when there exists some vector u, ||u|] < B, for which

»— hi : i
LS rinse (44) is not excessively large.

236

17.3

Multiclass, Ranking, and Complex Prediction Problems

Structured Output Prediction

Structured output prediction problems are multiclass problems in which ) is
very large but is endowed with a predefined structure. The structure plays a
key role in constructing efficient algorithms. To motivate structured learning
problems, consider the problem of optical character recognition (OCR). Suppose
we receive an image of some handwritten word and would like to predict which
word is written in the image. To simplify the setting, suppose we know how to
segment the image into a sequence of images, each of which contains a patch of
the image corresponding to a single letter. Therefore, V is the set of sequences

of images and ) is the set of sequences of letters. Note that the size of ) grows

exponentially with the maximal length of a word. An example of an image x

corresponding to the label y = “workable” is given in the following.

rh

To tackle structure prediction we can rely on the family of linear predictors
described in the previous section. In particular, we need to define a reasonable
loss function for the problem, A, as well as a good class-sensitive feature mapping,
WV. By “good” we mean a feature mapping that will lead to a low approximation
error for the class of linear predictors with respect to V and A. Once we do this,
we can rely, for example, on the SGD learning algorithm defined in the previous
section.

However, the huge size of Y poses several challenges:

1. To apply the multiclass prediction we need to solve a maximization problem
over Y. How can we predict efficiently when ) is so large?

2. How do we train w efficiently? In particular, to apply the SGD rule we again
need to solve a maximization problem over ).

3. How can we avoid overfitting?

In the previous section we have already shown that the sample complexity of
learning a linear multiclass predictor does not depend explicitly on the number
of classes. We just need to make sure that the norm of the range of is not too
large. This will take care of the overfitting problem. To tackle the computational
challenges we rely on the structure of the problem, and define the functions YW and
A so that calculating the maximization problems in the definition of hy and in
the SGD algorithm can be performed efficiently. In the following we demonstrate
one way to achieve these goals for the OCR task mentioned previously.

To simplify the presentation, let us assume that all the words in Y are of length
r and that the number of different letters in our alphabet is g. Let y and y’ be two

17.3 Structured Output Prediction 237

words (i.e., sequences of letters) in Y. We define the function A(y’,y) to be the

average number of letters that are different in y’ and y, namely, FS yan Ley. Ay']-
Next, let us define a class-sensitive feature mapping W(x, y). It will be conve-

nient to think about x as a matrix of size n x r, where n is the number of pixels

in each image, and r is the number of images in the sequence. The j’th column

of x corresponds to the j’th image in the sequence (encoded as a vector of gray

level values of pixels). The dimension of the range of W is set to be d=nq+q’.
The first ng feature functions are “type 1” features and take the form:

I<
Wijalsy) = ; Ss it Uy,=5)-
t=1

That is, we sum the value of the i’th pixel only over the images for which y
assigns the letter 7. The triple index (i, 7,1) indicates that we are dealing with
feature (7, j) of type 1. Intuitively, such features can capture pixels in the image
whose gray level values are indicative of a certain letter. The second type of
features take the form

1X<
Wij2%y) = r Ss Ay,=i) Tyy,_1=5)-
t=2

That is, we sum the number of times the letter 7 follows the letter j. Intuitively,
these features can capture rules like “It is likely to see the pair ‘qu’ in a word”
or “It is unlikely to see the pair ‘rz’ in a word.” Of course, some of these features
will not be very useful, so the goal of the learning process is to assign weights to
features by learning the vector w, so that the weighted score will give us a good
prediction via
hw(x) = argmax (w, U(x,y)).
yey

It is left to show how to solve the optimization problem in the definition
of hw(x) efficiently, as well as how to solve the optimization problem in the
definition of g in the SGD algorithm. We can do this by applying a dynamic
programming procedure. We describe the procedure for solving the maximization
in the definition of hw and leave as an exercise the maximization problem in the
definition of 7 in the SGD algorithm.

To derive the dynamic programming procedure, let us first observe that we
can write

V(x,y) = 30 Ox, yes yet)
t=1

for an appropriate @ : X x [q] x [q| U {0} > R¢, and for simplicity we assume
that yo is always equal to 0. Indeed, each feature function V;,;,1 can be written
in terms of

GACX Yes Yt-1) = Vit Uy, <9),


238

17.4

Multiclass, Ranking, and Complex Prediction Problems

while the feature function U;,;.2 can be written in terms of
Pig,2(%, Ye, Ye-1) = Uy, =a] Uy. =,)-
Therefore, the prediction can be written as
hw (x) = argmax So lw, o(x, Yes Ye—-1))- (17.4)
yeY

In the following we derive a dynamic programming procedure that solves every
problem of the form given in Equation (17.4). The procedure will maintain a
matrix M € R®” such that

,

Myr= max So (w, $(x, ye, 4e-1))-

t=1

Clearly, the maximum of (w, Y(x,y)) equals max, M,,-. Furthermore, we can
calculate M in a recursive manner:

Mg = max (My,r1 + (w, (x, ,8"))) (17.5)

This yields the following procedure:

Dynamic Programming for Calculating hy(x) as Given
in Equation (17.4)

input: a matrix x € R”” and a vector w
initialize:
foreach s € [{q]
Moa = (w, (x, 5,—1))
for 7 =2,...,r
foreach s € [{q]
set M,,, as in Equation (17.5)
set I,,, to be the s’ that maximizes Equation (17.5)
set y, = argmax, M,
for 7 =r, r—1,...,2
set Yr—-1 = Ty,,7
output: y = (y1,---, Yr)

Ranking

Ranking is the problem of ordering a set of instances according to their “rele-
vance.” A typical application is ordering results of a search engine according to
their relevance to the query. Another example is a system that monitors elec-
tronic transactions and should alert for possible fraudulent transactions. Such a
system should order transactions according to how suspicious they are.

Formally, let ¥* = UP, ¥" be the set of all sequences of instances from

17.4 Ranking 239

& of arbitrary length. A ranking hypothesis, h, is a function that receives a
sequence of instances X = (x),...,x,) € ¥*, and returns a permutation of [r].
It is more convenient to let the output of h be a vector y € R", where by
sorting the elements of y we obtain the permutation over [r]. We denote by
m(y) the permutation over [r] induced by y. For example, for r = 5, the vector
y = (2, 1, 6,—1, 0.5) induces the permutation m(y) = (4, 3, 5, 1, 2). That is,
if we sort y in an ascending order, then we obtain the vector (—1, 0.5, 1, 2, 6).
Now, 7(y); is the position of y; in the sorted vector (—1, 0.5, 1, 2, 6). This
notation reflects that the top-ranked instances are those that achieve the highest
values in 1(y).

In the notation of our PAC learning model, the examples domain is Z =
Us (4" x R”), and the hypothesis class, H, is some set of ranking hypotheses.
We next turn to describe loss functions for ranking. There are many possible ways
to define such loss functions, and here we list a few examples. In all the examples
we define ¢(h, (X,y)) = A(h(), y), for some function A : UY ,(R” x R") > Ry.
e 0-1 Ranking loss: A(y’,y) is zero if y and y’ induce exactly the same
ranking and A(y’,y) = 1 otherwise. That is, A(y’,y) = Itn(y)za(y))- Such
a loss function is almost never used in practice as it does not distinguish

between the case in which z(y’) is almost equal to 7(y) and the case in
which z(y’) is completely different from 7(y).

e Kendall-Tau Loss: We count the number of pairs (i,j) that are in different
order in the two permutations. This can be written as

2 rolor
Aty’,y) = r(r—1) Ss Ss Usign(y{—y)) Asign(yi—yy)]*
i=1 j=itl

This loss function is more useful than the 0-1 loss as it reflects the level of
similarity between the two rankings.

e Normalized Discounted Cumulative Gain (NDCG): This measure em-
phasizes the correctness at the top of the list by using a monotonically
nondecreasing discount function D : N > R,. We first define a discounted

cumulative gain measure:
r
Gy.y) =o Da@y):) vi.
i=1

In words, if we interpret y; as a score of the “true relevance” of item i, then
we take a weighted sum of the relevance of the elements, while the weight
of y; is determined on the basis of the position of 7 in 7(y’). Assuming that
all elements of y are nonnegative, it is easy to verify that 0 < G(y’,y) <
G(y, y). We can therefore define a normalized discounted cumulative gain
by the ratio G(y’, y)/G(y, y), and the corresponding loss function would
be

r

' Gly',y) 1 '
AVY) =1— Gay = yyy Le Per) = Demlv’):)) we

i=1

240

17.4.1

Multiclass, Ranking, and Complex Prediction Problems

We can easily see that A(y’,y) € [0,1] and that A(y’,y) = 0 whenever
my’) = n(y).

A typical way to define the discount function is by
ifie {r-k+1,...,r}

1
D(i) _ es

0 otherwise

where k <r is a parameter. This means that we care more about elements
that are ranked higher, and we completely ignore elements that are not at
the top-k ranked elements. The NDCG measure is often used to evaluate
the performance of search engines since in such applications it makes sense
completely to ignore elements that are not at the top of the ranking.

Once we have a hypothesis class and a ranking loss function, we can learn a
ranking function using the ERM rule. However, from the computational point of
view, the resulting optimization problem might be hard to solve. We next discuss
how to learn linear predictors for ranking.

Linear Predictors for Ranking

A natural way to define a ranking function is by projecting the instances onto
some vector w and then outputting the resulting scalars as our representation
of the ranking function. That is, assuming that VY C R¢, for every w € R¢ we
define a ranking function

hw((X1,---;Xr)) = ((w,x1),-.., (w,x,)). (17.6)

As we discussed in Chapter 16, we can also apply a feature mapping that maps
instances into some feature space and then takes the inner products with w in the
feature space. For simplicity, we focus on the simpler form as in Equation (17.6).

Given some W Cc R¢, we can now define the hypothesis class Hw = {hw :
w € W}. Once we have defined this hypothesis class, and have chosen a ranking
loss function, we can apply the ERM rule as follows: Given a training set, S =
(X1,y1),---;(Xm;Ym), where each (X;,y;) is in (VY x R)", for some r; € N, we
should search w € W that minimizes the empirical loss, )>;” , A(hw (Xi), Yi)
As in the case of binary classification, for many loss functions this problem is
computationally hard, and we therefore turn to describe convex surrogate loss
functions. We describe the surrogates for the Kendall tau loss and for the NDCG
loss.

A Hinge Loss for the Kendall Tau Loss Function:
We can think of the Kendall tau loss as an average of 0—1 losses for each pair.
In particular, for every (i,j) we can rewrite

Usign(y{—y))Asign(yi—us)] = Usign(yi—ys)(ul—y) <0]

17.4 Ranking 241

In our case, yj — yi, = (w, x; — xj). It follows that we can use the hinge loss upper
bound as follows:

Usign(yi—v) )(vf—vj) so] <<  max {0, 1 — sign (yi — yj) (w, xs — x;)}.

Taking the average over the pairs we obtain the following surrogate convex loss
for the Kendall tau loss function:

r-l or
A(hw(®).¥) < A SSP max (0,1 ~sigm(ys — yy) (woes —35)}-
rr) i=l j=itl

The right-hand side is convex with respect to w and upper bounds the Kendall
tau loss. It is also a p-Lipschitz function with parameter p < max;,; ||x; — x;||.

A Hinge Loss for the NDCG Loss Function:

The NDCG loss function depends on the predicted ranking vector y’ € R" via
the permutation it induces. To derive a surrogate loss function we first make
the following observation. Let V be the set of all permutations of [r] encoded as
vectors; namely, each v € V is a vector in [r]" such that for all i # j we have
vu; # vj. Then (see Exercise 4),

ty’) = argmax ) > v; yf. (17.7)

veV {1

Let us denote U(X, v) = )0j_ vixi; it follows that

1 (hw(X)) = argmax ) > uj (Ww, Xi)

veV 1
r
= argmax ( w, y UiXi
vev i=1

= argmax(w, U(x, v)).
veV
On the basis of this observation, we can use the generalized hinge loss for cost-
sensitive multiclass classification as a surrogate loss function for the NDCG loss
as follows:

Ali (3).¥) < A(bw().y) + (Ww, UR, (hw ())) — (wr, WR aLy)))
< max [A(v.¥) + (w, WX, v)) = (w, WOR, (9)))]

r
= mé A(y, Ui, — i +X;)]. 17.8
max |A(v,y) + a 3 — 7(y):) (Ww, x:) (17.8)
i=

The right-hand side is a convex function with respect to w.

We can now solve the learning problem using SGD as described in Section 17.2.5.
The main computational bottleneck is calculating a subgradient of the loss func-
tion, which is equivalent to finding v that achieves the maximum in Equa-

tion (17.8) (see Claim 14.6). Using the definition of the NDCG loss, this is

242

Multiclass, Ranking, and Complex Prediction Problems

equivalent to solving the problem

r
argmin ) (aii + B; D(v)),
veV 721
where a; = —(w,x;) and 8; = y:/G(y,y). We can think of this problem a little
bit differently by defining a matrix A € R™” where

Ajj = ja; + D(J) Bi-

Now, let us think about each j as a “worker,” each i as a “task,” and Ajj as
the cost of assigning task i to worker 7. With this view, the problem of finding
v becomes the problem of finding an assignment of the tasks to workers of
minimal cost. This problem is called “the assignment problem” and can be solved
efficiently. One particular algorithm is the “Hungarian method” (Kuhn 1955).
ignment problem is using linear programming. To

Another way to solve the ¢

do so, let us first write the assignment problem as

argmin Ss Ajj Big (17.9)

BER” jj=1

r
s.t. Vi € [r], SO Bi; =1
j=l

,
vi € Ir], SO Bi =1
i=1

Vi,j, Bi; € {0,1}

A matrix B that satisfies the constraints in the preceding optimization problem
is called a permutation matrix. This is because the constraints guarantee that
there is at most a single entry of each row that equals 1 and a single entry of each
column that equals 1. Therefore, the matrix B corresponds to the permutation
v €V defined by v; = j for the single index j that satisfies B;,; = 1.

The preceding optimization is still not a linear program because of the com-
binatorial constraint B;,; € {0,1}. However, as it turns out, this constraint is
redundant — if we solve the optimization problem while simply omitting the
combinatorial constraint, then we are still guaranteed that there is an optimal
solution that will satisfy this constraint. This is formalized later.

Denote (A, B) = iy A;,;B;,;. Then, Equation (17.9) is the problem of mini-
mizing (A, B) such that B is a permutation matrix.

A matrix B € R”” is called doubly stochastic if all elements of B are non-
negative, the sum of each row of B is 1, and the sum of each column of B is 1.
Therefore, solving Equation (17.9) without the constraints B;,; € {0,1} is the

problem

argmin(A,B) s.t. B is a doubly stochastic matrix. (17.10)
BeR™r

17.5

17.5 Bipartite Ranking and Multivariate Performance Measures 243

The following claim states that every doubly stochastic matrix is a convex
combination of permutation matrices.

CLAIM 17.3 ((Birkhoff 1946, Von Neumann 1953)) The set of doubly stochastic
matrices in R™" is the convex hull of the set of permutation matrices in R™".

On the basis of the claim, we easily obtain the following:

LEMMA 17.4 There exists an optimal solution of Equation (17.10) that is also
an optimal solution of Equation (17.9).

Proof Let B be a solution of Equation (17.10). Then, by Claim 17.3, we can
write B = 30; 7%iC;, where each C; is a permutation matrix, each 7; > 0, and
>); % = 1. Since all the C; are also doubly stochastic, we clearly have that
(A, B) < (A, C;) for every i. We claim that there is some i for which (A, B) =
(A, C;). This must be true since otherwise, if for every i (A, B) < (A, Cj), we
would have that

(A, B) = (4d70) = lA, Ci) > So 7i(A, B) = (A,B),

which cannot hold. We have thus shown that some permutation matrix, C;,
satisfies (A,B) = (A,C;). But, since for every other permutation matrix C we
have (A, B) < (A,C) we conclude that C; is an optimal solution of both Equa-
tion (17.9) and Equation (17.10).

Bipartite Ranking and Multivariate Performance Measures

In the previous section we described the problem of ranking. We used a vector
y €R’ for representing an order over the elements x1,...,X,. If all elements in y
are different from each other, then y specifies a full order over [r]. However, if two
elements of y attain the same value, y; = y; for i # j, then y can only specify a
partial order over [r]. In such a case, we say that x; and x, are of equal relevance
according to y. In the extreme case, y € {+1}", which means that each x; is
either relevant or nonrelevant. This setting is often called “bipartite ranking.” For
example, in the fraud detection application mentioned in the previous section,

each transaction is labeled as either fraudulent (y; = 1) or benign (y; = —1).

Seemingly, we can solve the bipartite ranking problem by learning a binary
classifier, applying it on each instance, and putting the positive ones at the top
of the ranked list. However, this may lead to poor results as the goal of a binary
learner is usually to minimize the zero-one loss (or some surrogate of it), while the
goal of a ranker might be significantly different. To illustrate this, consider again
the problem of fraud detection. Usually, most of the transactions are benign (say
99.9%). Therefore, a binary classifier that predicts “benign” on all transactions
will have a zero-one error of 0.1%. While this is a very small number, the resulting
predictor is meaningless for the fraud detection application. The crux of the


244

Multiclass, Ranking, and Complex Prediction Problems

problem stems from the inadequacy of the zero-one loss for what we are really

interested in. A more adequate perform

ance measure should take into account

the predictions over the entire set of instances. For example, in the previous

section we have defined the NDCG loss,

which emphasizes the correctness of the

top-ranked items. In this section we describe additional loss functions that are

specifically adequate for bipartite ranking problems.

As in the previous section, we are given
and we predict a ranking vector y’ € R"

a sequence of instances, X = (x1,...,Xr),
. The feedback vector is y € {+1}". We

define a loss that depends on y’ and y and depends on a threshold 6 € R. This

threshold transforms the vector y’ € R” i

nto the vector (sign(y/—@),..., sign(y}.—

0)) € {+1}". Usually, the value of @ is set to be 0. However, as we will see, we

sometimes set 6 while taking into account additional constraints on the problem.

The loss functions we define in the following depend on the following 4 num-

bers:

True positives:

False positives: b = |{i: y; = —
False negatives: c= |{i: y, = +1 Asign(y;

True negatives: d= |{i: y; = —

The recall (a.k.a. sensitivity) of a
positives y’ “catches,” namely, ane: T

a=|{i:y=+1Asign(y) — 0) = +1
‘ en eae (17.11)

(v6) =—1}

A sign(y; — 0) = —1}|

prediction vector is the fraction of true

he precision is the fraction of correct

predictions among the positive labels we predict, namely, ane: The specificity

is the fraction of true negatives that our predictor “catches,” namely, a

Note that as we decrease @ the recal

increases (attaining the value 1 when

@ = —oo). On the other hand, the precision and the specificity usually decrease

as we decrease 6. Therefore, there is a tr

adeoff between precision and recall, and

we can control it by changing 6. The loss functions defined in the following use

various techniques for combining both t

he precision and recall.

e Averaging sensitivity and specificity: This measure is the average of the

sensitivity and specificity, namely,

3 ( a4. as): This is also the accuracy

ate

on positive examples averaged wi

h the accuracy on negative examples.

Here, we set 6 = 0 and the corresponding loss function is A(y’,y) =

1 d
1-5 (at + as):

e F\-score: The F, score is the harmonic mean of the precision and recall:

2
T
Precision

z+—. Its maximal value
+ Recall

(of 1) is obtained when both precision

and recall are 1, and its minimal value (of 0) is obtained whenever one of

them is 0 (even if the other one is 1). The F, score can be written using

the numbers a, b, c as follows; Fy
loss function becomes A(y’, y) =

e Fs-score: It is like F, score, but we attach 6? times more importance to

recall than to precision, that is,

= wate Again, we set 9 = 0, and the
1-F,.
2
+e. It can also be written as

Precision Recall

17.5.1

17.5 Bipartite Ranking and Multivariate Performance Measures 245

2
Fg = aa Again, we set 0 = 0, and the loss function becomes

Alyy) =1— Fy.

e Recall at k: We measure the recall while the prediction must contain at most
k positive labels. That is, we should set 6 so that a+b < k. This is conve-
nient, for example, in the application of a fraud detection system, where a
bank employee can only handle a small number of suspicious transactions.

e Precision at k: We measure the precision while the prediction must contain
at least k positive labels. That is, we should set 0 so that a+b>k.

The measures defined previously are often referred to as multivariate perfor-

mance measures. Note that these measures are highly different from the average
b+d

atbtcetd*

tioned example of fraud detection, when 99.9% of the examples are negatively

zero-one loss, which in the preceding notation equals In the aforemen-

labeled, the zero-one loss of predicting that all the examples are negatives is
0.1%. In contrast, the recall of such prediction is 0 and hence the F, score is also
0, which means that the corresponding loss will be 1.

Linear Predictors for Bipartite Ranking

We next describe how to train linear predictors for bipartite ranking. As in the
previous section, a linear predictor for ranking is defined to be

hw (X) = ((w,x1),..., (W, X,)).

The corresponding loss function is one of the multivariate performance measures
described before. The loss function depends on y’ = hy(X) via the binary vector
it induces, which we denote by

b(y’) = (sign(y, — 4),..., sign(y/.-—6)) € {41}". (17.12)

As in the previous section, to facilitate an efficient algorithm we derive a convex
surrogate loss function on A. The derivation is similar to the derivation of the

generalized hinge loss for the NDCG ranking loss, as described in the previous
section.

Our first observation is that for all the values of @ defined before, there is some
V C {+1}" such that b(y’) can be rewritten as

r
b(y’) = argmax viy,- 17.13
(y') = argme > yh, (17.13)

This is clearly true for the case 6 = 0 if we choose V = {+1}". The two measures
for which @ is not taken to be 0 are precision at k and recall at k. For precision

at k we can take V to be the set V>,, containing all vectors in {+1}" whose
number of ones is at least k. For recall at k, we can take V to be Vcx, which is
defined analogously. See Exercise 5.

246

Multiclass, Ranking, and Complex Prediction Problems

Once we have defined b as in Equation (17.13), we can easily derive a convex
surrogate loss as follows. Assuming that y € V, we have that

A(hw(%),y) = A(b(hw(X)),¥)

< A(b(lv(3))-¥) + (bi (w(®)) — 4) (w,x:)
< max |A(v,y)+ Cr — yi) (w,xi)| . (17.14)

veV
i=l

The right-hand side is a convex function with respect to w.

We can now solve the learning problem using SGD as described in Section 17.2.5.
The main computational bottleneck is calculating a subgradient of the loss func-
tion, which is equivalent to finding v that achieves the maximum in Equa-
tion (17.14) (see Claim 14.6).

In the following we describe how to find this maximizer efficiently for any
performance measure that can be written as a function of the numbers a, b, c, d

given in Equation (17.11), and for which the set V contains all elements in {+1}"
for which the values of a,b satisfy some constraints. For example, for “recall at
k” the set V is all vectors for which a+b <k.

The idea is as follows. For any a,b € [r], let
Yap ={v : {iru =1lAy=Yl=a |{i: 4, =1Ay=—-1}|=b}.

Any vector v € V falls into 4, for some a,b € [r]. Furthermore, if Ya» V
is not empty for some a,b € [r] then Yaw nVv = Va.b- Therefore, we can search
within each Y,) that has a nonempty intersection with V separately, and then
take the optimal value. The key observation is that once we are searching only
within Y,.», the value of A is fixed so we only need to maximize the expression

max So vilw, Xi).
VvEVa.b Fay

Suppose the examples are sorted so that (w,x1) > --- > (w,x,). Then, it is
easy to verify that we would like to set v; to be positive for the smallest indices
i. Doing this, with the constraint on a,b, amounts to setting vj; = 1 for the a
top ranked positive examples and for the b top-ranked negative examples. This
yields the following procedure.

17.6

17.7

17.6 Summary 247

Solving Equation (17.14)

input:
(x1,---5 Xr); (Yis---5 Yr), Wi VA
assumptions:

A is a function of a, b, c, d
V contains all vectors for which f(a,b) = 1 for some function f

initialize:

P=(|{i: yi =1}),N =|{i: yi = —-1}|

p= ((w,X1),...,(W,X,)), a* = —00

sort examples so that 1 > M2 > +++ > by

let i1,...,ip be the (sorted) indices of the positive examples

let j1,...,jn be the (sorted) indices of the negative examples
for a=0,1,...,P

c=P-a

for b= 0,1,...,N such that f(a,b) =1

d=N-b

calculate A using a, b, c, d

set U1,...,Up S.t. Uj, SU, = Uj . =U
and the rest of the elements of v equal —1
seta=A+ an Vi fli
if a> a*
a®*=a,v*=v
output v*

Summary

Many real world supervised learning problems can be cast as learning a multiclass
predictor. We started the chapter by introducing reductions of multiclass learning
to binary learning. We then described and analyzed the family of linear predictors
for multiclass learning. We have shown how this family can be used even if the
number of classes is extremely large, as long as we have an adequate structure
on the problem. Finally, we have described ranking problems. In Chapter 29 we
study the sample complexity of multiclass learning in more detail.

Bibliographic Remarks

The One-versus-All and All-Pairs approach reductions have been unified un-
der the framework of Error Correction Output Codes (ECOC) (Dietterich &
Bakiri 1995, Allwein, Schapire & Singer 2000). There are also other types of re-
ductions such as tree-based classifiers (see, for example, Beygelzimer, Langford
& Ravikumar (2007)). The limitations of reduction techniques have been studied

248

17.8

Multiclass, Ranking, and Complex Prediction Problems

in (Daniely et al. 2011, Daniely, Sabato & Shwartz 2012). See also Chapter 29,
in which we analyze the sample complexity of multiclass learning.

Direct approaches to multiclass learning with linear predictors have been stud-
ied in (Vapnik 1998, Weston & Watkins 1999, Crammer & Singer 2001). In par-
ticular, the multivector construction is due to Crammer & Singer (2001).

Collins (2000) has shown how to apply the Perceptron algorithm for structured

output problems. See also Collins

(2002). A related approach is discriminative

learning of conditional random fields; see Lafferty, McCallum & Pereira (2001).

Structured output SVM has been s

udied in (Weston, Chapelle, Vapnik, Elisseeff

& Schélkopf 2002, Taskar, Guestrin & Koller 2003, Tsochantaridis, Hofmann,

Joachims & Altun 2004).
The dynamic procedure we have

resented for calculating the prediction hy (x)

in the structured output section is similar to the forward-backward variables
calculated by the Viterbi procedure in HMMs (see, for instance, (Rabiner &
Juang 1986)). More generally, solving the maximization problem in structured

output is closely related to the problem of inference in graphical models (see, for

example, Koller & Friedman (2009
Chapelle, Le & Smola (2007) pro;

))-

posed to learn a ranking function with respect

to the NDCG loss using ideas from structured output learning. They also ob-

served that the maximization prob

lem in the definition of the generalized hinge

loss is equivalent to the assignmen

problem.

Agarwal & Roth (2005) analyzed the sample complexity of bipartite ranking.
Joachims (2005) studied the applicability of structured output SVM to bipartite
ranking with multivariate performance measures.

Exercises

1. Consider a set S' of examples in R” x [k] for which there exist vectors p1,,..., Lp

such that every example (x,y) € S' falls within a ball centered at 2, whose
radius is r > 1. Assume also that for every i # j, ||u; — 4;|| = 4r. Con-
sider concatenating each instance by the constant 1 and then applying the
multivector construction, namely,

U(x,y)=[ 0,..., 0 ,21,---,2n,1, 0,...,0 ].
—leECToe OOOO i OO”
ERW-Dinth) eR™4+1 ER —v)(nt4)

Show that there exists a vector w € R*"+ such that ¢(w, (x, y)) = 0 for
every (x,y) € S.

Hint: Observe that for every example (x,y) € S we can write x = pw, + v for
some ||v|| <r. Now, take w = [wi,...,w,], where w; = [w;, —||1;||?/2]-

2. Multiclass Perceptron: Consider the following algorithm:

. Generalize the dynamic programming procedure given in Section 17.3 for solv-

17.8 Exercises 249

Multiclass Batch Perceptron

Input:
A training set (x1, 41),---;(%m:Ym)
A class-sensitive feature mapping V : X¥ x Y > R¢
Initialize: w) = (0,...,0) € R?
For ¢ = 1,2,...
If GiandyAy st. (w,U(x;,y;)) < (w, U(x, y))) then
wt) = w + U(x; y:) — U(xi, y)
else
output w!)

Prove the following:

THEOREM 17.5 Assume that there exists w* such that for alli and for all
y #y it holds that (w*, U(x;, yi)) > (w*, U(x;, y)) +1. Let R = maxj,y ||U(x;, y:)—

W(x, y)||. Then, the multiclass Perceptron algorithm stops after at most (R||w* ||)?
iterations, and when it stops it holds that Vi € [m], y; = argmax, (w), U(x;,y)).

ing the maximization problem given in the definition of h in the SGD proce-
dure for multiclass prediction. You can assume that A(y’, y) = 7/_, (yj, ys)
for some arbitrary function 6.

4. Prove that Equation (17.7) holds.

on

Show that the two definitions of 7 as defined in Equation (17.12) and Equa-
tion (17.13) are indeed equivalent for all the multivariate performance mea-
sures.

18

Decision Trees

A decision tree is a predictor, h : & — J, that predicts the label associated with
an instance x by traveling from a root node of a tree to a leaf. For simplicity
we focus on the binary classification setting, namely, VY = {0,1}, but decision
trees can be applied for other prediction problems as well. At each node on the
root-to-leaf path, the successor child is chosen on the basis of a splitting of the
input space. Usually, the splitting is based on one of the features of x or on a
predefined set of splitting rules. A leaf contains a specific label. An example of
a decision tree for the papayas example (described in Chapter 2) is given in the
following:

pale green to pale yellow

gives slightly to palm pressure

To check if a given papaya is tasty or not, the decision tree first examines
the color of the Papaya. If this color is not in the range pale green to pale
yellow, then the tree immediately predicts that the papaya is not tasty without
additional tests. Otherwise, the tree turns to examine the softness of the papaya.
If the softness level of the papaya is such that it gives slightly to palm pressure,
the decision tree predicts that the papaya is tasty. Otherwise, the prediction is
“not-tasty.” The preceding example underscores one of the main advantages of
decision trees — the resulting classifier is very simple to understand and interpret.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

18.1

18.1 Sample Complexity

Sample Complexity

A popular split:
value of a single

Hence, if we al

of infinite VC d

principle descri

‘0 one cell. It follows that a tree with k leaves can shatter

To avoid overfitting, we can rely on the minimum descri

ing rule at internal nodes of the tree is base
eature. That is, we move to the right or left

In such cases, we can think of a decision

ow decision trees of arbitrary size, we obtai.
imension. Such an approach can easily lead

on thresh

ree aS as

a set of k
n a hypot
to overfitt:

ption leng

hand fits the data well while on the other hand is not too large.

For simplicity, we will assume that Y = {0,1}¢. In other words, eac!

251

olding the

child of the node on
he basis of 1), <9], where i € [d] is the index of the relevant feature and 6 € R
is the threshold.
he instance space, Y¥ = R®, into cells, where each leaf of

litting of

he tree corresponds

instances.
hesis class
ing.

h (MDL)

ed in Chapter 7, and aim at learning a decision tree that on one

h instance

is a vector of d bits. In that case, threshold

corresponds to a splitting rule of the form 1,,

ing the value of a single feature
=1) for some i = [d]. For instance,

we can model the “papaya decision tree” ear.

ier by assuming that a

parameterized by a two-

imensional bit vector x € {0,1}?, where

papaya is
he bit x,

represents whether the color is pale green to

represents whether the softness is gives slight.

this re

Softness? can be replaced with 1j,,—1). While this is a big simplification, the

algorit
general

With the aforementioned simp.

finite,
can be

27. Uni

he number of examples we need

resentation, the node Color? can be replaced with 1),,—1), and the node

pale yellow or not, and the bit x2
ly to palm pressure or not. With

hms and analysis we provide in the fo
cases.

represented by a decision tree with 2

Exercise 1). Therefore, the VC dimension of the class is 27, which means that

ifying assumption, the hypothesis class becomes
ut is still very large. In particular, any classifier from {0,1}4 to {0,1}

to PAC learn the hypothesis class grows with

lowing can be extended to more

4 leaves and depth of d+ 1 (see

ess d is very small, this is a huge number of examples.

To overcome this obstacle, we rely on the MDL scheme described in Chapter 7.
The underlying prior knowledge is that we should prefer smaller trees over larger
rees. To formalize this intuition, we first need to define a description language
for decision trees, which is prefix free and requires fewer bits for smaller decision
rees. Here is one possible way: A tree with n nodes will be described in n + 1
blocks, each of size log,(d + 3) bits. The first n blocks encode the nodes of the
ree, in a depth-first order (preorder), and the last block marks the end of the

code. Each block indicates whether the current node is:

e An internal node of the form 1,1) for some i € [d]

e A leaf whose value is 1

e A leaf whose value is 0

e End of the code

252

18.2

Decision Trees

Overall, there are d+ 3 options, hence we need logs(d + 3) bits to describe each
block.

Assuming each internal node has two children,! it is not hard to show that
this is a prefix-free encoding of the tree, and that the description length of a tree
with n nodes is (n + 1) logs(d + 3).

By Theorem 7.7 we have that with probability of at least 1 — 6 over a sample
of size m, for every n and every decision tree h € H with n nodes it holds that

(n + 1) logs(d + 3) + log(2/6)
2m ,

(18.1)

Lp(h) < Ls(h) 4 /

This bound performs a tradeoff: on the one hand, we expect larger, more complex
decision trees to have a smaller training risk, Lg(h), but the respective value of
n will be larger. On the other hand, smaller decision trees will have a smaller
value of n, but Lsg(h) might be larger. Our hope (or prior knowledge) is that we
can find a decision tree with both low empirical risk, Ls(h), and a number of
nodes n not too high. Our bound indicates that such a tree will have low true
risk, Lp(h).

Decision Tree Algorithms

The bound on Lp(h) given in Equation (18.1) suggests a learning rule for decision
trees — search for a tree that minimizes the right-hand side of Equation (18.1).
Unfortunately, it turns out that solving this problem is computationally hard.?
Consequently, practical decision tree learning algorithms are based on heuristics
such as a greedy approach, where the tree is constructed gradually, and locally
optimal decisions are made at the construction of each node. Such algorithms
cannot guarantee to return the globally optimal decision tree but tend to work
reasonably well in practice.

A general framework for growing a decision tree is as follows. We start with
a tree with a single leaf (the root) and assign this leaf a label according to a
majority vote among all labels over the training set. We now perform a series of
iterations. On each iteration, we examine the effect of splitting a single leaf. We

define some “gain” measure that quantifies the improvement due to this split.

Then, among all possible splits, we either choose the one that maximizes the
gain and perform it, or choose not to split the leaf at all.

In the following we provide a possible implementation. It is based on a popular
decision tree algorithm known as “ID3” (short for “Iterative Dichotomizer 3”).
We describe the algorithm for the case of binary features, namely, V = {0,1}4,

1 We may assume this without loss of generality, because if a decision node has only one
child, we can replace the node by its child without affecting the predictions of the decision
tree.

2 More precisely, if NPAP then no algorithm can solve Equation (18.1) in time polynomial
in n,d, and m.

18.2.1

18.2 Decision Tree Algorithms 253

and therefore all splitting rules are of the form 1j,,-1) for some feature i € [d].
We discuss the case of real valued features in Section 18.2.3.

The algorithm works by recursive calls, with the initial call being ID3(S, [d]),
and returns a decision tree. In the pseudocode that follows, we use a call to a
procedure Gain(S, i), which receives a training set S and an index i and evaluates
the gain of a split of the tree according to the ith feature. We describe several

gain measures in Section 18.2.1.

1D3(S, A)

INPUT: training set S, feature subset A C [d]
if all examples in S are labeled by 1, return a leaf 1
if all examples in S are labeled by 0, return a leaf 0
if A =, return a leaf whose value = majority of labels in S
else :
Let j = argmax;¢ 4 Gain(S, i)
if all examples in S have the same label
Return a leaf whose value = majority of labels in S
else
Let T; be the tree returned by ID3({(x,y) € S: a; =1},A\ {j}).
Let T be the tree returned by ID3({(x,y) € S: 2; = 0}, A \ {j}).

Return the tree:

Implementations of the Gain Measure

Different algorithms use different implementations of Gain(S, i). Here we present
three. We use the notation Ps[F] to denote the probability that an event holds
with respect to the uniform distribution over S.

Train Error: The simplest definition of gain is the decrease in training error.
Formally, let C(a) = min{a, 1—a}. Note that the training error before splitting on
feature i is C(Ps[y = 1]), since we took a majority vote among labels. Similarly,
the error after splitting on feature i is

Pfr: = 1) C(Ply = Ife: = 1) + Blas = 0}C(Ply = Ie = 0).

Therefore, we can define Gain to be the difference between the two, namely,
Gain(S,i) := ce y=1)

— (Bli = 1) C(Bly = Alas = 1) + Ble = O1C (Rly = Ari = 0))) -


254

18.2.2

Decision Trees

Information Gain: Another popular gain measure that is used in the ID3
and C4.5 algorithms of Quinlan (1993) is the information gain. The information
gain is the difference between the entropy of the label before and after the split,
and is achieved by replacing the function C' in the previous expression by the
entropy function,

C(a) = —alog(a) — (1 — a) log(1 — a).

Gini Index: Yet another definition of a gain, which is used by the CART
algorithm of Breiman, Friedman, Olshen & Stone (1984), is the Gini index,

C(a) = 2a(1 — a).

Both the information gain and the Gini index are smooth and concave upper
bounds of the train error. These properties can be advantageous in some situa-
tions (see, for example, Kearns & Mansour (1996)).

Pruning

The ID3 algorithm described previously still suffers from a big problem: The
returned tree will usually be very large. Such trees may have low empirical risk,
but their true risk will tend to be high — both according to our theoretical
analysis, and in practice. One solution is to limit the number of iterations of ID3,
leading to a tree with a bounded number of nodes. Another common solution is
to prune the tree after it is built, hoping to reduce it to a much smaller tree,
but still with a similar empirical error. Theoretically, according to the bound in
Equation (18.1), if we can make n much smaller without increasing Ls(h) by
much, we are likely to get a decision tree with a smaller true risk.

Usually, the pruning is performed by a bottom-up walk on the tree. Each node
might be replaced with one of its subtrees or with a leaf, based on some bound
or estimate of Lp(h) (for example, the bound in Equation (18.1)). A pseudocode
of a common template is given in the following.

Generic Tree Pruning Procedure

input:
function f(T,m) (bound/estimate for the generalization error
of a decision tree T, based on a sample of size m),
tree T.
foreach node j in a bottom-up walk on T (from leaves to root):
find T’ which minimizes f(I’,m), where T’ is any of the following:
the current tree after replacing node j with a leaf 1.
the current tree after replacing node j with a leaf 0.
the current tree after replacing node j with its left subtree.

the current tree after replacing node j with its right subtree.

the current tree.
let T:=T".


18.3 Random Forests 255

18.2.3 Threshold-Based Splitting Rules for Real-Valued Features

In the previous section we have described an algorithm for growing a decision
ree assuming that the features are binary and the splitting rules are of the
form 1h,,-1;. We now extend this result to the case of real-valued features and
hreshold-based splitting rules, namely, tj, <9}. Such splitting rules yield decision
stumps, and we have studied them in Chapter 10.

The basic idea is to reduce the problem to the case of binary features as
follows. Let x1,...,Xm be the instances of the training set. For each real-valued
feature i, sort the instances so that 21, <--- < 4m. Define a set of thresholds
,i:+++,Om4i1¢ Such that 05; € (%;,;,0;41,;) (where we use the convention x; =
—oo and &m41,; = 00). Finally, for each i and j we define the binary feature
th.; <6; ;]- Once we have constructed these binary features, we can run the ID3
procedure described in the previous section. It is easy to verify that for any

decision tree with threshold-based splitting rules over the original real-valued
features there exists a decision tree over the constructed binary features with
he same training error and the same number of nodes.

If the original number of real-valued features is d and the number of examples
is m, then the number of constructed binary features becomes dm. Calculating

he Gain of each feature might therefore take O(dm?) operations. However, using

a more clever implementation, the runtime can be reduced to O(dm log(m)). The
idea is similar to the implementation of ERM for decision stumps as described
in Section 10.1.1.

18.3 Random Forests

As mentioned before, the class of decision trees of arbitrary size has infinite VC
dimension. We therefore restricted the size of the decision tree. Another way
to reduce the danger of overfitting is by constructing an ensemble of trees. In
particular, in the following we describe the method of random forests, introduced
by Breiman (2001).

A random forest is a classifier consisting of a collection of decision trees, where
each tree is constructed by applying an algorithm A on the training set S and
an additional random vector, 0, where @ is sampled i.i.d. from some distribution.

The prediction of the random forest is obtained by a majority vote over the
predictions of the individual trees.

To specify a particular random forest, we need to define the algorithm A and
the distribution over 6. There are many ways to do this and here we describe one
particular option. We generate 0 as follows. First, we take a random subsample
from S with replacements; namely, we sample a new training set S’ of size m/

using the uniform distribution over S. Second, we construct a sequence [;, I2,...,
where each J; is a subset of [d] of size k, which is generated by sampling uniformly
at random elements from [{d]. All these random variables form the vector 6. Then,

256

18.4

18.5

18.6

Decision Trees

the algorithm A grows a decision tree (e.g., using the ID3 algorithm) based on
the sample S$’, where at each splitting stage of the algorithm, the algorithm is
restricted to choosing a feature that maximizes Gain from the set J;. Intuitively,
if k is small, this restriction may prevent overfitting.

Summary

Decision trees are very intuitive predictors. Typically, if a human programmer
creates a predictor it will look like a decision tree. We have shown that the VC
dimension of decision trees with k leaves is k and proposed the MDL paradigm
for learning decision trees. The main problem with decision trees is that they
are computationally hard to learn; therefore we described several heuristic pro-
cedures for training them.

Bibliographic Remarks

Many algorithms for learning decision trees (such as ID3 and C4.5) have been
derived by Quinlan (1986). The CART algorithm is due to Breiman et al. (1984).
Random forests were introduced by Breiman (2001). For additional reading we
refer the reader to (Hastie, Tibshirani & Friedman 2001, Rokach 2007).

The proof of the hardness of training decision trees is given in Hyafil & Rivest

(1976).

Exercises

1. 1. Show that any binary classifier h : {0,1}¢ ++ {0,1} can be implemented
as a decision tree of height at most d+ 1, with internal nodes of the form
(a; = 0?) for some i € {1,...,d}.
2. Conclude that the VC dimension of the class of decision trees over the
domain {0, 1}4 is 2¢.
2. (Suboptimality of ID3)

Consider the following training set, where Y = {0,1}° and Y = {0,1}:
((1,1,1),1)
((1, 0,0), 1)
((1, 1,0), 0)
((0, 0, 1),0)

Suppose we wish to use this training set in order to build a decision tree of
depth 2 (i.e., for each input we are allowed to ask two questions of the form
(x; = 0?) before deciding on the label).

18.6 Exercises 257

1. Suppose we run the ID3 algorithm up to depth 2 (namely, we pick the root
node and its children according to the algorithm, but instead of keeping
on with the recursion, we stop and pick leaves according to the majority
label in each subtree). Assume that the subroutine used to measure the
quality of each feature is based on the entropy function (so we measure the
information gain), and that if two features get the same score, one of them
is picked arbitrarily. Show that the training error of the resulting decision
tree is at least 1/4.

2. Find a decision tree of depth 2 that attains zero training error.

19

19.1

Nearest Neighbor

Nearest Neighbor algorithms are among the simplest of all machine learning
algorithms. The idea is to memorize the training set and then to predict the
label of any new instance on the basis of the labels of its closest neighbors in
the training set. The rationale behind such a method is based on the assumption
that the features that are used to describe the domain points are relevant to
their labelings in a way that makes close-by points likely to have the same label.
Furthermore, in some situations, even when the training set is immense, finding
a nearest neighbor can be done extremely fast (for example, when the training
set is the entire Web and distances are based on links).

Note that, in contrast with the algorithmic paradigms that we have discussed
so far, like ERM, SRM, MDL, or RLM, that are determined by some hypothesis
class, H, the Nearest Neighbor method figures out a label on any test point

without searching for a predictor within some predefined class of functions.

In this chapter we describe Nearest Neighbor methods for classification and
regression problems. We analyze their performance for the simple case of binary
classification and discuss the efficiency of implementing these methods.

k Nearest Neighbors

Throughout the entire chapter we assume that our instance domain, 1’, is en-
dowed with a metric function p. That is, p: & x X > Risa function that returns
the distance between any two elements of 4. For example, if X = R? then p can
be the Euclidean distance, p(x, x’) = ||x — x’|| = ya: — ai)?

Let S = (x1, 41),---;(Km;Ym) be a sequence of training examples. For each
x € X, let m(x),.
distance to x, p(x,x;). That is, for all i < m,

,Mm(X) be a reordering of {1,...,m} according to their

P(X, Xm, (3)) S PUK Xai (x))+

For a number k, the k-NN rule for binary classification is defined as follows:

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

19.2

19.2 Analysis 259

Figure 19.1 An illustration of the decision boundaries of the 1-NN rule. The points
depicted are the sample points, and the predicted label of any new point will be the
label of the sample point in the center of the cell it belongs to. These cells are called a
Voronoi Tessellation of the space.

k-NN

input: a training sample S = (x1, y1),..-, (Xm, Ym)
output: for every point x € %,

return the majority label among {Yyz,(x) : 4 < k}

When k = 1, we have the 1-NN rule:
hs(X) = Yr (x):

A geometric illustration of the 1-NN rule is given in Figure 19.1.

For regression problems, namely, YY = R, one can define the prediction to be
the average target of the k nearest neighbors. That is, hs(x) = ty, Yr (x)*
More generally, for some function @ : (¥ x Y)* > Y, the k-NN rule with respect
to @ is:

Ts(x) = b ((%as(x)s Yara (a) s+ 2+ + (Kage) Yn (xe))) + (19.1)

It is easy to verify that we can cast the prediction by majority of labels (for
classification) or by the averaged target (for regression) as in Equation (19.1) by
an appropriate choice of ¢. The generality can lead to other rules; for example, if
Y =R, we can take a weighted average of the targets according to the distance
from x:

PAX, Xn (x))
nsx) = Oe sc:

k
i=l YVj-1 p(x, Xn;(x))

Analysis

Since the NN rules are such natural learning methods, their generalization prop-
erties have been extensively studied. Most previous results are asymptotic con-
sistency results, analyzing the performance of NN rules when the sample size, m,

260

19.2.1

Nearest Neighbor

goes to infinity, and the rate of convergence depends on the underlying distribu-
tion. As we have argued in Section 7.4, this type of analysis is not satisfactory.
One would like to learn from finite training samples and to understand the gen-
eralization performance as a function of the size of such finite training sets and
clear prior assumptions on the data distribution. We therefore provide a finite-
sample analysis of the 1-NN rule, showing how the error decreases as a function
of m and how it depends on properties of the distribution. We will also explain
how the analysis can be generalized to k-NN rules for arbitrary values of k. In
particular, the analysis specifies the number of examples required to achieve a
true error of 2L-p(h*) + €, where h* is the Bayes optimal hypothesis, assuming
that the labeling rule is “well behaved” (in a sense we will define later).

A Generalization Bound for the 1-NN Rule

We now analyze the true error of the 1-NN rule for binary classification with
the 0-1 loss, namely, Y = {0,1} and ¢(h, (x,y)) = Incezyj- We also assume
throughout the analysis that ¥ = (0, 1]¢ and p is the Euclidean distance.

We start by introducing some notation. Let D be a distribution over ¥ x ).

Let Dy denote the induced marginal distribution over ¥ and let 7: R¢ > R be
the conditional probability! over the labels, that is,

(x) = Ply = 1|x].

Recall that the Bayes optimal rule (that is, the hypothesis that minimizes Lp(h)

over all functions) is
h*(X) = Uy(x)>1/2]-

We assume that the conditional probability function 7 is c-Lipschitz for some
c > 0: Namely, for all x,x’ € Y, |n(x) —n(x’)| < ¢||x—x’||. In other words, this
assumption means that if two vectors are close to each other then their labels
are likely to be the same.

The following lemma applies the Lipschitzness of the conditional probability
function to upper bound the true error of the 1-NN rule as a function of the
expected distance between each test instance and its nearest neighbor in the
training set.

LEMMA 19.1 Let ¥ = [0,1]¢,Y = {0,1}, and D be a distribution over X x Y
for which the conditional probability function, n, is a c-Lipschitz function. Let
S = (x1, y1),---;(%m,Ym) be an i.i.d. sample and let hg be its corresponding
1-NN hypothesis. Let h* be the Bayes optimal rule for n. Then,

<Ballvlhs)] S2L0(h) +e. Blix nce):

1 Formally, Ply = 1|x] = lims.o Do eB ony , where B(x, 65) is a ball of radius 5
centered around x.

19.2 Analysis 261

Proof Since Lp(hs) = Ecx,y)~p[lns(x)¢y]], We obtain that Es[Lp(hs)] is the
probability to sample a training set S and an additional example (x,y), such
that the label of 71(x) is different from y. In other words, we can first sample
m unlabeled examples, S,, = (X1,...,;Xm), according to Dy, and an additional
unlabeled example, x ~ Dy, then find 7; (x) to be the nearest neighbor of x in
S,, and finally sample y ~ (x) and Ym, (x) ~ 7(71(x)). It follows that

E[Lo(hs)] = (yay

S2~D¥ X~Dx yrn(x)sy/~n(71 (x))

= E P yAy'l|- (19.2)

© SanDEx~Dw | y~n(x).y! nlm (6)

We next upper bound Pyvn(x).y~n(x ly 4 y'] for any two domain points x, x’:
ly A y'] = n(x’) = n(&)) + (L = (n(x)

yoontx) yan!) :
(n(x) — n(x) + n(x'))(L = n(x))
+ (1 = n(x) + n(x) — n(x’))n(x)
= 2n(x)(1 — n(x) + (nx) — n(x'))(2n@&) — 1).

Using |27(x) — 1] < 1 and the assumption that 7 is c-Lipschitz, we obtain that

the probability is at most:

P [y A y'] < 2n&)(1 — n(x) + € |x — x’.
yon(x),y/~n(x’)

Plugging this into Equation (19.2) we conclude that

ElLo(hs)] S E2n(x)A—n(x))] +¢ Elle ~ Xm alll:

Ss x

Finally, the error of the Bayes optimal classifier is

Lp(h*) = Elmin{n(x),1— (x)}] 2 Eln(x)(1 — n(x))]-

Combining the preceding two inequalities concludes our proof.

The next step is to bound the expected distance between a random x and its
closest element in S. We first need the following general probability lemma. The
lemma bounds the probability weight of subsets that are not hit by a random
sample, as a function of the size of that sample.

LEMMA 19.2. Let Ci,...,C, be a collection of subsets of some domain set, X.
Let S be a sequence of m points sampled i.i.d. according to some probability
distribution, D over X. Then,

262

Nearest Neighbor

Proof From the linearity of expectation, we can rewrite:

E} S° Piel} = DPICIE [hevns-0]

“C;NS=0

Next, for each i we have
E [Hens] = PIGS = 0) = (1 -PIG)™ <ePOIm,

Combining the preceding two equations we get

E > Jo < > P[CijeMCl™ <r max P[Ci] eW PICs) m,
aCinS= i=

Finally, by a standard calculus, maxg ae"? < a“ and this concludes the proof.

Equipped with the preceding lemmas we are now ready to state and prove the
main result of this section — an upper bound on the expected error of the 1-NN
learning rule.

THEOREM 19.3 Let X = [0,1]*,Y = {0,1}, and D be a distribution over ¥ x Y
for which the conditional probability function, n, is a c-Lipschitz function. Let
hg denote the result of applying the 1-NN rule to a sample S ~D™. Then,

1
E._ [Lp(hs)] < 2Lp(h*) +4eVdm Gt,

SoD™
Proof Fix some € = 1/T, for some integer T, let r = T¢ and let Cy,...,C, be the
cover of the set ¥ using boxes of length e: Namely, for every (a1,..., aa) € [T]4,

there exists a set C; of the form {x : Vj, aj € [(aj —1)/T,a;/T]}. An illustration
for d = 2, T = 5 and the set corresponding to a = (2, 4) is given in the following.

1

1

For each x, x’ in the same box we have ||x—x’|| < Vde. Otherwise, ||x—x’|| < Vd.
Therefore,

Elk — Xm coll s BP U G)jva+P) U Gieval,

:Cins=0 ECINSAO

and by combining Lemma 19.2 with the trivial bound PU;-c.nsz0 Ci] < 1 we
get that

Ex —xz,coll $ V4(f +9)-

19.2.2

19.2 Analysis 263

Since the number of boxes is r = (1/e)¢ we get that

d ed
Ellx— xn olll < Vd (A +6).

me

Combining the preceding with Lemma 19.1 we obtain that
* id et
B[Lo(hs)] < 2Lo(h*) +evd (2S +e).
Finally, setting ¢ = 2m~'/(4+)) and noting that
gd e-d gd 9d pp_d/(d+1)

rE
me me

= m-MEM (1/642) < 4m)

2a i/(at1)

we conclude our proof.

The theorem implies that if we first fix the data-generating distribution an

then let m go to infinity, then the error of the 1-NN rule converges to twice the
Bayes error. The analysis can be generalized to larger values of k, showing tha’
the expected error of the k-NN rule converges to (1 + /8/k) times the error 0:
the Bayes classifier. This is formalized in Theorem 19.5, whose proof is left as a

guided exercise.

The “Curse of Dimensionality”

The upper bound given in Theorem 19.3 grows with c (the Lipschitz coefficient
of 7) and with d, the Euclidean dimension of the domain set ¥. In fact, it is easy
to see that a necessary condition for the last term in Theorem 19.3 to be smaller
than ¢€ is that m > (4c Vd/e)4+!. That is, the size of the training set should
increase exponentially with the dimension. The following theorem tells us that
this is not just an artifact of our upper bound, but, for some distributions, this
amount of examples is indeed necessary for learning with the NN rule.

THEOREM 19.4 For any c > 1, and every learning rule, L, there exists a
distribution over (0, 1]¢ x {0,1}, such that n(x) is c-Lipschitz, the Bayes error of
the distribution is 0, but for sample sizes m < (c+ 1)4/2, the true error of the
rule L is greater than 1/4.

Proof Fix any values of ¢ and d. Let G? be the grid on [0, 1] with distance of
1/c between points on the grid. That is, each point on the grid is of the form
(ai/c, -
points on this grid are at least 1/c apart, any function 7 : GR — [0,1] is a
c-Lipschitz function. It follows that the set of all c-Lipschitz functions over G?

.,@a/C) where a; is in {0,..., c—1,c}. Note that, since any two distinct

contains the set of ail binary valued functions over that domain. We can therefore
invoke the No-Free-Lunch result (Theorem 5.1) to obtain a lower bound on the
needed sample sizes for learning that class. The number of points on the grid is
(e+ 1)4; hence, if m < (e+ 1)4/2, Theorem 5.1 implies the lower bound we are
after.


264

19.3

19.4

19.5

Nearest Neighbor

The exponential dependence on the dimension is known as the curse of di-
mensionality. As we saw, the 1-NN rule might fail if the number of examples is
smaller than 9((c+1)“). Therefore, while the 1-NN rule does not restrict itself to
a predefined set of hypotheses, it still relies on some prior knowledge — its success
depends on the assumption that the dimension and the Lipschitz constant of the
underlying distribution, 7, are not too high.

Efficient Implementation*

Nearest Neighbor is a learning-by-memorization type of rule. It requires the
entire training data set to be stored, and at test time, we need to scan the entire
data set in order to find the neighbors. The time of applying the NN rule is
therefore @(dm). This leads to expensive computation at test time.

When d is small, several results from the field of computational geometry have
proposed data structures that enable to apply the NN rule in time o(d°) log(m)).
However, the space required by these data structures is roughly m0, which
makes these methods impractical for larger values of d.

To overcome this problem, it was suggested to improve the search method by
allowing an approzimate search. Formally, an r-approximate search procedure is
guaranteed to retrieve a point within distance of at most r times the distance

to the nearest neighbor. Three popular approximate algorithms for NN are the
kd-tree, balltrees, and locality-sensitive hashing (LSH). We refer the reader, for
example, to (Shakhnarovich, Darrell & Indyk 2006).

Summary

The k-NN rule is a very simple learning algorithm that relies on the assumption
that “things that look alike must be alike.” We formalized this intuition using
the Lipschitzness of the conditional probability. We have shown that with a suf
ficiently large training set, the risk of the 1-NN is upper bounded by twice the
risk of the Bayes optimal rule. We have also derived a lower bound that shows
the “curse of dimensionality” — the required sample size might increase expo-
nentially with the dimension. As a result, NN is usually performed in practice
after a dimensionality reduction preprocessing step. We discuss dimensionality
reduction techniques later on in Chapter 23.

Bibliographic Remarks
Cover & Hart (1967) gave the first analysis of 1-NN, showing that its risk con-

verges to twice the Bayes optimal error under mild conditions. Following a lemma
due to Stone (1977), Devroye & Gyérfi (1985) have shown that the k-NN rule

19.6

19.6 Exercises 265

is consistent (with respect to the hypothesis class of all functions from R¢ to
{0, 1}). A good presentation of the analysis is given in the book of Devroye et al.
(1996). Here, we give a finite sample guarantee that explicitly underscores the
prior assumption on the distribution. See Section 7.4 for a discussion on con-
sistency results. Finally, Gottlieb, Kontorovich & Krauthgamer (2010) derived
another finite sample bound for NN that is more similar to VC bounds.

Exercises

In this exercise we will prove the following theorem for the k-NN rule.

THEOREM 19.5 Let X = [0,1]¢,V = {0,1}, and D be a distribution over X x Y
for which the conditional probability function, n, is a c-Lipschitz function. Let hs
denote the result of applying the k-NN rule to a sample S ~ D™, where k > 10.
Let h* be the Bayes optimal hypothesis. Then,

E[Lp(hs)] < (: + V3) Lp(h*) + (6cva+ k) mV (dtd)

1. Prove the following lemma.

LEMMA 19.6 Let C,...,C, be a collection of subsets of some domain set,
X. Let S be a sequence of m points sampled i.t.d. according to some probability
distribution, D over X&. Then, for every k > 2,

ark
cS | DU FIGI) < T
i:|CiNS|<k
Hints:
e Show that
E] Do PIG) = DUPICIB ICN S| <4].
i:|C{NS|<k i=l

e Fix some i and suppose that k < P[C;] m/2. Use Chernoff’s bound to show
that

B[ICN S| <k] <B[ICi S| < P[Ci]m/2] < 7 PIC) m/8

w< + to show that for such i we have

Use the inequality max, ae

< k] < P[CiJe7 MC m/8 < 8

me

PCIE (IC: ns

Conclude the proof by using the fact that for the case k > P[C;]m/2 we
clearly have:

PICP (ICN S

2/2

<k) < PIC] <

266 Nearest Neighbor

2. We use the notation y ~ pas ashorthand for “y is a Bernoulli random variable
with expected value p.” Prove the following lemma:

LEMMA 19.7 Letk > 10 and let Z,..., Z,, be independent Bernoulli random

variables with P[Z; = 1] = p;. Denote p= i Yo, pi and p! = ty Z;. Show

that
8
E P 1, <|{1 —} P al :
Za, EY F Upsi/a] < ( + Vi) wel F Ups1/2]]
Hints:
W.1Lo.g. assume that p < 1/2. Then, Py~p[y 4 lpsi/a]] = p. Let y! = Uprsia-
e Show that

EP p=. P_ [p! > 1/2] — 2p).
aya elt FUP = oP > VAN — 2p)

e Use Chernoff’s bound (Lemma B.3) to show that
Pip’ > 1/2) < en kPh(ap—1)
where
h(a) = (1 + a) log(1 + a) — a.

e Toconclude the proof of the lemma, you can rely on the following inequality
(without proving it): For every p € [0,1/2] and k > 10:
(1 — 2p) enBP +E los2P)4+1) < 8

Ss RP

3. Fix some p,p’ € [0,1] and y’ € {0,1}. Show that
PlyA4y)]< P yAyl+\p-p'l.
y~p y~p

4. Conclude the proof of the theorem according to the following steps:
e As in the proof of Theorem 19.3, six some € > 0 and let Ci,...,C;, be the

cover of the set 4 using boxes of length ¢. For each x,x’ in the same
box we have ||x — x’|| < Vde. Otherwise, ||x — x’|| < 2 Vd. Show that

E[Lp(hs)| SE) > PIC

Ss
s|CiNS|<k

+max P  [hs(x) Ay | Vi € [A |X — xn Goll Seva]. (19.3)
i S,(x,y)

e Bound the first summand using Lemma 19.6.

e To bound the second summand, let us fix S|, and x such that all the k
neighbors of x in S|, are at distance of at most e/d from x. W.Lo.g
assume that the k NN are x1,...,xx. Denote p; = 7(x;) and let p =
ti Pi- Use Exercise 3 to show that

vey, wees) Fyls wey, pts) # ¥] + Ip — n()|-

19.6 Exercises 267

W.Lo.g. assume that p < 1/2. Now use Lemma 19.7 to show that

e Show that
EP, Aie>s/a) # yl = p = min{p, 1p} < min{n(x), 1—n(x)} + |p—n()].

e Combine all the preceding to obtain that the second summand in Equa-
tion (19.3) is bounded by

(: + 3) Lp(h*) +3ceva.

e Use r = (2/e)¢ to obtain that:

E[Lp(hs)] < (: + Vi) Lp(h*) +3ceVd+ 22/e)tk

m
Set € = 2m~/(4+ and use
Gem VD Ja 4 Bm-V OD < (Ged +) mM
e

to conclude the proof.

20

Neural Networks

An artificial neural network is a model of computation inspired by the structure

of neural networks in the brain. In simplified models of the brain, it consists of

a large number of basic computing devices (neurons) that are connected to each

other in a complex communication network, through which the brain is able to

carry out highly complex computations. Artificial neural networks are formal

computation cons

ructs that are modeled after this computation paradigm.

Learning with neural networks was proposed in the mid-20th century. It yields

an effective learning paradigm and

edge performance
A neural networ!
to neurons and e

as input a weighted sum of the out:

on several learni:

ges correspond

has recently been shown to achieve cutting-
ng tasks.

k can be described as a directed graph whose nodes correspond

o links between them. Each neuron receives
puts of the neurons connected to its incoming

edges. We focus on feedforward networks in which the underlying graph does not

contain cycles.

In the context o:
network

practical

consisting of efficiently implementable predictors.

The caveat is that the problem of training such hypothesis

learning, we can define a hypothesis class consisting of neural

Section 20.3, every predictor over n variables that can

he size of the network is the number of nodes in it. It
of hypothesis classes of neural networks of polynomial
learning tasks, in which our goal is to learn predic

ple complexity of learning such hypothesis classes is also boun
size of the network. Hence, it seems that this is the ultimate
we would want to adapt, in the sense that i
plexity and has the minimal approximation error among all

predictors, where all the hypotheses share the underlying graph struc-
ure of the network and differ in the weights over edges. As we will show in

be implemented in time

T(n) can also be expressed as a neural network predictor of size O(T'(n)”), where

follows that the family
size can suffice for all
ors which can be

implemented efficiently. Furthermore, in Section 20.4 we will show that the sam-

ed in terms of the

earning paradigm

both has a polynomial sample com-

hypothesis classes

classes of neural net-

work predictors is computationally hard. This will be formalized in Section 20.5.

A widely used heuristic for training neura’
work we studied in Chapter 14. There, we
learner if the loss function is convex. In neural networks, the

networks relies on the SGD frame-
have shown that SGD is a successful

oss function is

highly nonconvex. Nevertheless, we can still implement the SGD algorithm and

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

20.1

20.1 Feedforward Neural Networks 269

hope it will find a reasonable solution (as happens to be the case in several
practical tasks). In Section 20.6 we describe how to implement SGD for neural
networks. In particular, the most complicated operation is the calculation of the
gradient of the loss function with respect to the parameters of the network. We
present the backpropagation algorithm that efficiently calculates the gradient.

Feedforward Neural Networks

The idea behind neural networks is that many neurons can be joined together
by communication links to carry out complex computations. It is common to
describe the structure of a neural network as a graph whose nodes are the neurons
and each (directed) edge in the graph links the output of some neuron to the
input of another neuron. We will restrict our attention to feedforward network
structures in which the underlying graph does not contain cycles.

A feedforward neural network is described by a directed acyclic graph, G =
(V, £), and a weight function over the edges, w : E — R. Nodes of the graph
correspond to neurons. Each single neuron is modeled as a simple scalar func-
tion, g : R — R. We will focus on three possible functions for o: the sign
function, o(a) = sign(a), the threshold function, o(a) = Iqso), and the sig-
moid function, o(a) = 1/(1+exp(—a)), which is a smooth approximation to the
threshold function. We call o the “activation” function of the neuron. Each edge

in the graph links the output of some neuron to the input of another neuron.

The input of a neuron is obtained by taking a weighted sum of the outputs of
all the neurons connected to it, where the weighting is according to w.

To simplify the description of the calculation performed by the network, we
further assume that the network is organized in layers. That is, the set of nodes
can be decomposed into a union of (nonempty) disjoint subsets, V = UL oV;,,
such that every edge in E connects some node in V;_, to some node in V,, for

some t € [T]. The bottom layer, Vo, is called the input layer. It contains n + 1
neurons, where n is the dimensionality of the input space. For every 7 € [n], the
output of neuron 7 in Vo is simply z;. The last neuron in Vo is the “constant”

neuron, which always outputs 1. We denote by v;,; the ith neuron of the tth layer
and by o;,;(x) the output of v;,; when the network is fed with the input vector x.
Therefore, for i € [n] we have 09,;(x) = 2; and for i = n+ 1 we have 09,;(x) = 1.
We now proceed with the calculation in a layer by layer manner. Suppose we
have calculated the outputs of the neurons at layer t. Then, we can calculate
the outputs of the neurons at layer t+ 1 as follows. Fix some v41,; € Vi4t.
Let 41,5 (Xx) denote the input to v;41,; when the network is fed with the input
vector x. Then,

a441,5 (Xx) = Ss w(t rs Ve+1,j)) Ctr (X),

r: (Ver,0e41,j EE

270

20.2

Neural Networks

and
o1+1,5(X) = 0 (a441,j(X))-

That is, the input to v,41,; is a weighted sum of the outputs of the neurons in V,
that are connected to v441,;, where weighting is according to w, and the output
of vz41,j is simply the application of the activation function o on its input.
Layers Vi,..., Vr—i are often called hidden layers. The top layer, Vr, is called
the output layer. In simple prediction problems the output layer contains a single
neuron whose output is the output of the network.
We refer to T as the number of layers in the network (excluding Vo), or the
“depth” of the network. The size of the network is |V|. The “width” of the
network is max; |V;|. An illustration of a layered feedforward neural network of

depth 2, size 10, and width 5, is given in the following. Note that there is a
neuron in the hidden layer that has no incoming edges. This neuron will output
the constant o(0).

Input Hidden Output
layer layer layer
(Vo) (i) (V2)

constant —|

Learning Neural Networks

Once we have specified a neural network by (V,E,o,w), we obtain a function
hy.p,0,w : R'Yl-! — RIVrI, Any set of such functions can serve as a hypothesis
class for learning. Usually, we define a hypothesis class of neural network predic-
tors by fixing the graph (V, £) as well as the activation function o and letting
the hypothesis class be all functions of the form hy,z,5,w for some w: E > R.
The triplet (V, E,c) is often called the architecture of the network. We denote
the hypothesis class by

Hyv,n,0 = {hv,z,cw : w is a mapping from E to R}. (20.1)

20.3

20.3 The Expressive Power of Neural Networks 271

That is, the parameters specifying a hypothesis in the hypothesis class are the
weights over the edges of the network.

We can now study the approximation error, estimation error, and optimization
error of such hypothesis classes. In Section 20.3 we study the approximation
error of Hy,g,>¢ by studying what type of functions hypotheses in Hy,z,, can
implement, in terms of the size of the underlying graph. In Section 20.4 we
study the estimation error of Hy,nz,,, for the case of binary classification (i.e.,
Vr = 1 and o is the sign function), by analyzing its VC dimension. Finally, in
Section 20.5 we show that it is computationally hard to learn the class Hy,z,0,
even if the underlying graph is small, and in Section 20.6 we present the most
commonly used heuristic for training Hy,n,c-

The Expressive Power of Neural Networks

In this section we study the expressive power of neural networks, namely, what
ype of functions can be implemented using a neural network. More concretely,
we will fix some architecture, V, £,o, and will study what functions hypotheses
in Hy.z,c can implement, as a function of the size of V.
We start the discussion with studying which type of Boolean functions (i.e.,

functions from {+1}" to {+1}) can be implemented by Hy,z,sign. Observe that

for every computer in which real numbers are stored using b bits, whenever we
calculate a function f : R” — R on such a computer we in fact calculate a

function g : {+1}" > {+1}°. Therefore, studying which Boolean functions can

be implemented by Hy,z,sign can tell us which functions can be implemented on

a computer that stores real numbers using 6 bits.
We begin with a simple claim, showing that without restricting the size of the

network, every Boolean function can be implemented using a neural network of
depth 2.

CLAIM 20.1 For every n, there exists a graph (V,E) of depth 2, such that
Hv,z,sign contains all functions from {+1}" to {£1}.

Proof We construct a graph with |Vo| = n+ 1,|Vil = 2" +1, and |V2| = 1. Let
E be all possible edges between adjacent layers. Now, let f : {41}” > {+1}

be some Boolean function. We need to show that we can adjust the weights so
that the network will implement f. Let uj,...,u,% be all vectors in {+1}”" on

which f outputs 1. Observe that for every i and every x € {+1}”, if x 4 uj
then (x, uj) <n — 2 and if x = u; then (x, u;) =n. It follows that the function
gi(x) = sign((x, uj) —n+1) equals 1 if and only if x = uj. It follows that we can

adapt the weights between Vo and Vj so that for every i € [k], the neuron v1;

implements the function g;(x). Next, we observe that f(x) is the disjunction of

272

Neural Networks

the functions g;(x), and therefore can be written as

f(x) = sign (dpa00 +k- ) ;

i=l

which concludes our proof.

The preceding claim shows that neural networks can implement any Boolean
function. However, this is a very weak property, as the size of the resulting

network might be exponentially large. In the construction given at the proof o:
Claim 20.1, the number of nodes in the hidden layer is exponentially large. This
is not an artifact of our proof, as stated in the following theorem.

THEOREM 20.2 For every n, let s(n) be the minimal integer such that there
exists a graph (V,E) with |V| = s(n) such that the hypothesis class Hv, x, sign
contains all the functions from {0,1}" to {0,1}. Then, s(n) is exponential in n.
Similar results hold for Hy,n,¢ where o is the sigmoid function.

Proof Suppose that for some (V, EZ) we have that Hy,z,sign contains all functions
rom {0,1}" to {0,1}. It follows that it can shatter the set of m = 2” vectors in
{0,1}" and hence the VC dimension of Hy,z sign is 2”. On the other hand, the
VC dimension of Hy,x,sign is bounded by O(|E|log(|E|)) < O(\V|8), as we wil
show in the next section. This implies that |V| > 0(2”/%), which concludes our
proof for the case of networks with the sign activation function. The proof for

he sigmoid case is analogous.

Remark 20.1 It is possible to derive a similar theorem for Hy,f,. for any o, as
ong as we restrict the weights so that it is possible to express every weight using
a number of bits which is bounded by a universal constant. We can even con-
sider hypothesis classes where different neurons can employ different activation
unctions, as long as the number of allowed activation functions is also finite.

Which functions can we express using a network of polynomial size? The pre-
ceding claim tells us that it is impossible to express all Boolean functions using
a network of polynomial size. On the positive side, in the following we show

hat all Boolean functions that can be calculated in time O(T(n)) can also be
expressed by a network of size O(T(n)).

THEOREM 20.3. Let T:N-— WN and for every n, let F, be the set of functions
that can be implemented using a Turing machine using runtime of at most T(n).
Then, there exist constants b,c € Ry such that for every n, there is a graph
(Vi, En) of size at most cT(n)? +b such that Hy,,,z,,,sign contains Fy.

The proof of this theorem relies on the relation between the time complexity
of programs and their circuit complexity (see, for example, Sipser (2006)). In a
nutshell, a Boolean circuit is a type of network in which the individual neurons

20.3.1

20.3 The Expressive Power of Neural Networks 273

implement conjunctions, disjunctions, and negation of their inputs. Circuit com-
plexity measures the size of Boolean circuits required to calculate functions. The
relation between time complexity and circuit complexity can be seen intuitively
as follows. We can model each step of the execution of a computer program as a
simple operation on its memory state. Therefore, the neurons at each layer of the
network will reflect the memory state of the computer at the corresponding time,
and the translation to the next layer of the network involves a simple calculation
that can be carried out by the network. To relate Boolean circuits to networks

with the sign activation function, we need to show that we can implement the
operations of conjunction, disjunction, and negation, using the sign activation

function. Clearly, we can implement the negation operator using the sign activa-
tion function. The following lemma shows that the sign activation function can
also implement conjunctions and disjunctions of its inputs.

LEMMA 20.4 Suppose that a neuron v, that implements the sign activation
function, has k incoming edges, connecting it to neurons whose outputs are in

{41}. Then, by adding one more edge, linking a “constant” neuron to v, and
by adjusting the weights on the edges to v, the output of v can implement the
conjunction or the disjunction of its inputs.

Proof Simply observe that if f : {+1}* {+1} is the conjunction func-
tion, f(x) = A;a;, then it can be written as f(x) = sign (1 —k+ yw wi).
Similarly, the disjunction function, f(x) = Vix, can be written as f(x) =

sign (x —1+ yw wi).

So far we have discussed Boolean functions. In Exercise 1 we show that neura

networks are universal approximators. That is, for every fixed precision param-
eter, € > 0, and every Lipschitz function f : [—1,1]" — [1,1], it is possible to
construct a network such that for every input x € [—1,1]”, the network outputs

a number between f(x) — € and f(x) + €. However, as in the case of Boolean
functions, the size of the network here again cannot be polynomial in n. This is
formalized in the following theorem, whose proof is a direct corollary of Theo-
rem 20.2 and is left as an exercise.

THEOREM 20.5 Fix some € (0,1). For every n, let s(n) be the minimal integer
such that there exists a graph (V, E) with |V| = s(n) such that the hypothesis class
Hyv,n,0, with o being the sigmoid function, can approximate, to within precision
of €, every 1-Lipschitz function f : [—1,1]" > [-1,1]. Then s(n) is exponential

mn.

Geometric Intuition

We next provide several geometric illustrations of functions f : R? > {+1}
and show how to express them using a neural network with the sign activation
function.

274

20.4

Neural Networks

Let us start with a depth 2 network, namely, a network with a single hidden
layer. Each neuron in the hidden layer implements a halfspace predictor. Then,
the single neuron at the output layer applies a halfspace on top of the binary
outputs of the neurons in the hidden layer. As we have shown before, a halfspace
can implement the conjunction function. Therefore, such networks contain all
hypotheses which are an intersection of k — 1 halfspaces, where & is the number
of neurons in the hidden layer; namely, they can express all convex polytopes
with k — 1 faces. An example of an intersection of 5 halfspaces is given in the
following.

We have shown that a neuron in layer V2 can implement a function that
indicates whether x is in some convex polytope. By adding one more layer, and
letting the neuron in the output layer implement the disjunction of its inputs,
we get a network that computes the union of polytopes. An illustration of such
a function is given in the following.

HENS

The Sample Complexity of Neural Networks

Next we discuss the sample complexity of learning the class Hy, z,,. Recall that
the fundamental theorem of learning tells us that the sample complexity of learn-
ing a hypothesis class of binary classifiers depends on its VC dimension. There-
fore, we focus on calculating the VC dimension of hypothesis classes of the form
Hv,£,0, where the output layer of the graph contains a single neuron.

We start with the sign ¢
the VC dimension of this cle
VC dimension should be order of |E|. This is indeed the case, as formalized by

tivation function, namely, with Hy,z,sign- What is

ss? Intuitively, since we learn |E| parameters, the

the following theorem.

THEOREM 20.6 The VC dimension of Hy,n,sign is O(|E|log(|E])).

20.4 The Sample Complexity of Neural Networks 275

Proof To simplify the notation throughout the proof, let us denote the hy-
pothesis class by H. Recall the definition of the growth function, 7(m), from
Section 6.5.1. This function measures maxocx:|c|=m |Hc|, where Hc is the re-
striction of H to functions from C to {0,1}. We can naturally extend the defi-
nition for a set of functions from 4 to some finite set Y, by letting Hc be the
restriction of H to functions from C to J, and keeping the definition of 77,(m)
intact.

Our neural network is defined by a layered graph. Let Vo,..., Vr be the layers
of the graph. Fix some t € [T]. By assigning different weights on the edges
between V;_; and V,, we obtain different functions from RIV!  {+1}!Yl. Let
H) be the class of all possible such mappings from RIY-1! > {+1} Ml, Then,
H can be written as a composition, H =H) o...0H™). In Exercise 4 we show

that the growth function of a composition of hypothesis classes is bounded by
the products of the growth functions of the individual class

s. Therefore,

T
Tu(m) < Il Tre) (Mm).
t=1

In addition, each H can be written as a product of function classes, H =
HOY x... x HOM), where each H+) is all functions from layer t— 1 to {1}
that the jth neuron of layer t can implement. In Exercise 3 we bound product
classes, and this yields
|Vel
Ti) (mM) < [TL eo (m).
i=l

Let d;,; be the number of edges that are headed to the ith neuron of layer t.
Since the neuron is a homogenous halfspace hypothesis and the VC dimension
of homogenous halfspaces is the dimension of their input, we have by Sauer’s
lemma that

di
Teeo(m) < (2) ” < (em).
Overall, we obtained that
mul) < (em)Zee = (em)lEl,

Now, assume that there are m shattered points. Then, we must have T(m) =
2™, from which we obtain

2" <(em)lZl = m<|E|log(em)/log(2).

The claim follows by Lemma A.2.

Next, we consider Hy,z,¢, where o is the sigmoid function. Surprisingly, it
turns out that the VC dimension of Hy,~,¢ is lower bounded by ((|E|*) (see
Exercise 5.) That is, the VC dimension is the number of tunable parameters
squared. It is also possible to upper bound the VC dimension by O(|V|? |E|?),
but the proof is beyond the scope of this book. In any cas

, since in practice

276

20.5

Neural Networks

we only consider networks in which the weights have a short representation as
floating point numbers with O(1) bits, by using the discretization trick we easily
obtain that such networks have a VC dimension of O(|E|), even if we use the
sigmoid activation function.

The Runtime of Learning Neural Networks

In the previous sections we have shown that the class of neural networks with an
underlying graph of polynomial size can express all functions that can be imple-
mented efficiently, and that the sample complexity has a favorable dependence
on the size of the network. In this section we turn to the analysis of the time
complexity of training neural networks.

We first show that it is NP hard to implement the ERM rule with respect to
Hv, ,sign even for networks with a single hidden layer that contain just 4 neurons
in the hidden layer.

THEOREM 20.7 Let k > 3. For every n, let (V,E) be a layered graph with n
input nodes, k + 1 nodes at the (single) hidden layer, where one of them is the
constant neuron, and a single output node. Then, it is NP hard to implement the
ERM rule with respect to Hy,x,sign-

The proof relies on a reduction from the k-coloring problem and is left as
Exercise 6.

One way around the preceding hardness result could be that for the purpose
of learning, it may suffice to find a predictor h € H with low empirical error,
not necessarily an exact ERM. However, it turns out that even the task of find-
ing weights that result in close-to-minimal empirical error is computationally
infeasible (see (Bartlett & Ben-David 2002)).

One may also wonder whether it may be possible to change the architecture
of the network so as to circumvent the hardness result. That is, maybe ERM
with respect to the original network structure is computationally hard but ERM

with respect to some other, larger, network may be implemented efficiently (see
Chapter 8 for examples of such cases). Another possibility is to use other acti-
vation functions (such as sigmoids, or any other type of efficiently computable

activation functions). There is a strong indication that all of such approaches

are doomed to fail. Indeed, under some cryptographic assumption, the problem

of learning intersections of halfspaces is known to be hard even in the repre-
sentation independent model of learning (see Klivans & Sherstov (2006)). This
implies that, under the same cryptographic assumption, any hypothesis class

which contains intersections of halfspaces cannot be learned efficiently.

A widely used heuristic for training neural networks relies on the SGD frame-
work we studied in Chapter 14. There, we have shown that SGD is a successful
learner if the loss function is convex. In neural networks, the loss function is
highly nonconvex. Nevertheless, we can still implement the SGD algorithm and

20.6

20.6 SGD and Backpropagation 277

hope it will find a reasonable solution (as happens to be the case in several
practical tasks).

SGD and Backpropagation

The problem of finding a hypothesis in Hy,z,, with a low risk amounts to the
problem of tuning the weights over the edges. In this section we show how to
apply a heuristic search for goo

weights using the SGD algorithm. Throughout

this section we assume that o is the sigmoid function, o(a) = 1/(1+ e~*), but

the derivation

holds for any differentiable scalar function.

Since E is a finite set, we can think of the weight function as a vector w € R!#I.

Suppose the network has n input neurons and & output neurons, and denote by

hw : R" > R*®
defined by w.

Let us denote by

the function calculated by the network if the weight function is

A(hw(x), y) the loss of predicting hyw(x) when

the target is y € ). For concreteness, we will take A to be the squared loss,

A(hw(x),y) =

5l|hw (x) — yl;

however, similar derivation can be obtained for

every differentiable function. Finally, given a distribution D over the examples

domain, R” x

R*, let Lp(w) be

the risk of the network, namely,

Lo(w) = E A(hw()¥)]-

(

Recall the SGD algorithm for minimizing the risk function Lp(w). We repeat

he pseudocode from Chapter 14 with a few modifications, which are relevant
o the neural network application because of the nonconvexity of the objective
function. First, while in Chapter 14 we initialized w to be the zero vector, here
we initialize w to be a randomly chosen vector with values close to zero. This
is because an initialization with the zero vector will lead all hidden neurons to
have the same weights (if the network is a full layered network). In addition,
he hope is that if we repeat the SGD procedure several times, where each time

we initialize the process with a new random vector, one of the runs will lead

o a good local minimum. Second, while a fixed step size, 7, is guaranteed to

be good enough for convex problems, here we utilize a variable step size, 7, as

defined in Section 14.4.2. Because of the nonconvexity of the loss function, the

choice of the sequence 7 is more significant, and it is tuned in practice by a trial

and error manner. Third, we output the best performing vector on a validation

set. In addition, it is sometimes helpful to add regularization on the weights,

with parameter A. That is, we try to minimize Lp(w) + 3 \wll?. Finally, the

gradient does not have a closed form solution. Instead, it is implemented using

the backpropagation algorithm, which will be described in the sequel.

278

Neural Networks

SGD for Neural Networks

parameters:

number of iterations T

step size sequence 71,12, ---, "Ir

regularization parameter \ > 0
input:

layered graph (V, £)

differentiable activation function 0: RR
initialize:

choose w) € RI#! at random

(from a distribution s.t. w') is close enough to 0)

for i =1,2,...,7

sample (x,y) ~ D

calculate gradient v; = backpropagation(x, y, w, (V, E),c)

update wt) = w — nj(vi + Aw)
output:

w is the best performing w“) on a validation set

Backpropagation

input:
example (x,y), weight vector w, layered graph (V, £),
activation function ¢: RR
initialize:
denote layers of the graph Vo,...,Vr where Vi = {vi1,---, Vt,e, }
define W;,;,; as the weight of (v1,5, Ur41,:)
(where we set Wii; = 0 if (vj, ve414) ¢ EB)

forward:
set O09 =X
for t
fori =1,

; kena
set ari = joy Wi-1,4,5 8-15
set 04,45 = o(az,i)

backward:
set Or =or—-y
for t=T—1,T—2,...,1
fori =1,...,k
oni = sary Wr Oteig 0 (Qr41,5)
output:

foreach edge (v~1,;, 024) € EB
set the partial derivative to 6; 0’ (a1) 01-1,


20.6 SGD and Backpropagation 279

Explaining How Backpropagation Calculates the Gradient:

We next explain how the backpropagation algorithm calculates the gradient of
the loss function on an example (x,y) with respect to the vector w. Let us first
recall a few definitions from vector calculus. Each element of the gradient is
the partial derivative with respect to the variable in w corresponding to one of
the edges of the network. Recall the definition of a partial derivative. Given a
function f : R” > R, the partial derivative with respect to the ith variable at w
is obtained by fixing the values of w1,..., Wi—1, Wi+1, Wn, Which yields the scalar
function g : R + R defined by g(a) = f((wi,.--,wi-1, Wi + @, Wi41,---,Wn)),
and then taking the derivative of g at 0. For a function with multiple outputs,
f:R" > R”, the Jacobian of f at w € R", denoted Jy(f), is the m x n matrix
whose i,j element is the partial derivative of f; : RR” > R w.r.t. its jth variable

at w. Note that ifm = 1 then the Jacobian matrix is the gradient of the function
(represented as a row vector). Two examples of Jacobian calculations, which we
will later use, are as follows.

e Let £(w) = Aw for Ac R™”. Then Jy(f) = A.
e For every n, we use the notation o to denote the function from R” to R”

which applies the sigmoid function element-wise. That is, a = 0(@) means

that for every i we have a; = o(6;) = Teco): It is easy to verify
that Jo(o) is a diagonal matrix whose (i,i) entry is o’(0;), where o’ is
the derivative function of the (scalar) sigmoid function, namely, o/(0;) =
Crete: We also use the notation diag(o’(@)) to denote this
matrix.

The chain rule for taking the derivative of a composition of functions can be
written in terms of the Jacobian as follows. Given two functions f : R” > R™

and g : R* — R®, we have that the Jacobian of the composition function,
(fog): R* > R”, at w, is

Jw (fog) = Jgow)(f) Jw(g)-
For example, for g(w) = Aw, where A € R™*, we have that
Jw(o 0g) = diag(o’(Aw)) A.

To describe the backpropagation algorithm, let us first decompose V into the
layers of the graph, V = U7_)V;. For every t, let us write Vi = {v1,1,-.., Usk}
where k, = |V;|. In addition, for every t denote Wi € R*+1-' a matrix which
gives a weight to every potential edge between V; and V;41. If the edge exists in
E then we set W;,;,; to be the weight, according to w, of the edge (v;,j, v:+1,i).
Otherwise, we add a “phantom” edge and set its weight to be zero, W;;,; = 0.
Since when calculating the partial derivative with respect to the weight of some
edge we fix all other weights, these additional “phantom” edges have no effect

on the partial derivative with respect to existing edges. It follows that we can
assume, without loss of generality, that all edges exist, that is, E = U,(Vi x Viz).

280

Neural Networks

Next, we discuss how to calculate the partial derivatives with respect to the
edges from V;_; to V;, namely, with respect to the elements in W;_1. Since we
fix all other weights of the network, it follows that the outputs of all the neurons
in V,_, are fixed numbers which do not depend on the weights in W;_,;. Denote
the corresponding vector by 0;_1. In addition, let us denote by ¢, : R* — R the
loss function of the subnetwork defined by layers V;,..., Vr as a function of the
outputs of the neurons in V;. The input to the neurons of V; can be written as
a, = W;,_10;_1 and the output of the neurons of V, is o, = o(a;). That is, for
every j we have o,,; = o(a;,;). We obtain that the loss, as a function of W;_1,
can be written as

ge(Wi-1) = &4 (04) = &(o(ar)) = (9 (Wi-104-1)).

It would be convenient to rewrite this as follows. Let w,-; € R*+-1** be the
column vector obtained by concatenating the rows of W;_1 and then taking the

transpose of the resulting long vector. Define by O;—1 the ky x (ky—1k;) matrix

of, 0 0
0 of; -- 0
On. = ; . |. (20.2)
0 0 Of-1

Then, W,_104-1 = O4_1 wt_1, so we can also write
ge(we-1) = €(o(Or-1 Wi-1))-
Therefore, applying the chain rule, we obtain that
Twrs(Gt) = To(O,.ws1) (lr) diag(o"(Or-1wi-1)) O11.
Using our notation we have 0; = o(O;—1w:-1) and a; = Oy—1 we-1, which yields
Jer, (Gt) = Jo, (Cr) diag(o'(ar)) Or-1.

Let us also denote 6; = Jo, (&). Then, we can further rewrite the preceding as

Tors (gt) = (61,1 a! (at) Of ees Stake a" (di,k,) Of) - (20.3)

It is left to calculate the vector 6; = Jo,(¢:) for every t. This is the gradient
of ¢; at o,. We calculate this in a recursive manner. First observe that for the
last layer we have that &p(u) = A(u,y), where A is the loss function. Since we
assume that A(u, y) = $||u—y||? we obtain that Ju(¢r) = (u—y). In particular,
Or = Jo, (lr) = (or — y). Next, note that

&(u) = fr41(o(Wru)).
Therefore, by the chain rule,

alle) = Jo(wruy (+1)diag(o’(Wiu))W1.

20.7

20.8

20.7 Summary 281

In particular,
51 = Jo, (C4) = Jo wor) (le+1)diag(a’(Wro,)) Wi
= To. (le41)diag(o’ (aryi1))W
= 6141 diag(o’(aryi))We.

In summary, we can first calculate the vectors {a;,0;} from the bottom of
the network to its top. Then, we calculate the vectors {6;} from the top of
the network back to its bottom. Once we have all of these vectors, the partial
derivatives are easily obtained using Equation (20.3). We have thus shown that.
the pseudocode of backpropagation indeed calculates the gradient.

Summary

Neural networks over graphs of size s(n) can be used to describe hypothesis
classes of all predictors that can be implemented in runtime of O(,/s(n)). We
have also shown that their sample complexity depends polynomially on s(n)
(specifically, it depends on the number of edges in the network). Therefore, classes
of neural network hypotheses seem to be an excellent choice. Regrettably, the
problem of training the network on the basis of training data is computationally
hard. We have presented the SGD framework as a heuristic approach for training
neural networks and described the backpropagation algorithm which efficiently

calculates the gradient of the loss function with respect to the weights over the
edges.

Bibliographic Remarks

Neural networks were extensively studied in the 1980s and early 1990s, but with
mixed empirical success. In recent years, a combination of algorithmic advance-
ments, as well as increasing computational power and data size, has led to a
breakthrough in the effectiveness of neural networks. In particular, “deep net-
works” (i.e., networks of more than 2 layers) have shown very impressive practical

performance on a variety of domains. A
works (Lecun & Bengio 1995), restricted

few examples include convolutional net-
Boltzmann machines (Hinton, Osindero

& Teh 2006), auto-encoders (Ranzato, Huang, Boureau & Lecun 2007, Bengio &

LeCun 2007, Collobert & Weston 2008,

Lee, Grosse, Ranganath & Ng 2009, Le,

Ranzato, Monga, Devin, Corrado, Chen, Dean & Ng 2012), and sum-product
networks (Livni, Shalev-Shwartz & Shamir 2013, Poon & Domingos 2011). See
also (Bengio 2009) and the references therein.

The expressive power of neural networks and the relation to circuit complexity
have been extensively studied in (Parberry 1994). For the analysis of the sample

complexity of neural networks we refer the reader to (Anthony & Bartlet 1999).
Our proof technique of Theorem 20.6 is due to Kakade and Tewari lecture notes.

282

20.9

Neural Networks

Klivans & Sherstov (2006) have shown that for any c > 0, intersections of n°

halfspaces over {+1}" are not efficiently PAC learnable, even if we allow repre-

sentation independent learning. This hardness result relies on the cryptographic
assumption that there is no polynomial time solution to the unique-shortest-

vector problem. As we have argued, this implies that there cannot be an efficient

algorithm for training neural networks, even if we allow larger networks or other

activation functions that can be implemented efficiently.

The backpropagation algorithm has been introduced in Rumelhart, Hinton &

Williams (1986).

Exercises

1. Neural Networks are universal approximators: Let f : [—1,1]” >
[-1,1] be a p-Lipschitz function. Fix some « > 0. Construct a neural net-
work N : [—1,1]” > [-1,1], with the sigmoid activation function, such that
for every x € [—1,1]" it holds that | f(x) — N(x)| <e.

Hint: Similarly to the proof of Theorem 19.3, partition [—1,1]” into small

boxes. Use the Lipschitzness of f to show that it is approximately constant

at each box. Finally, show that a neural network can first decide which box

the input vector
box.

2. Prove Theorem 2

Hint: For every

g:({-1,1)" > [-1,

f.

belongs to, and then predict the averaged value of f at that

0.5.
f : {-1,1}" > {-1,1} construct a 1-Lipschitz function

| such that if you can approximate g then you can express

3. Growth function of product: For i = 1,2, let F; be a set of functions from
&X to Y;. Define H = Fy, x Fo to be the Cartesian product class. That is, for

every fi; € Fi an

Prove that 74(m

fo € Fe, there exists h € H such that h(x) = (fi(x), fo(x)).
) S$ tr, (m) TF, (m).

4. Growth function of composition: Let F; be a set of functions from ¥

to Z and let Fo
composition cle

such that h(x) =

be a set of functions from Z to Y. Let H = Fo 0 Fy, be the
. That is, for every f1 € Fy and fg € Fo, there exists h © H
f2(fi(x)). Prove that t(m) < Tx, (m)rF, (m).

5. VC of sigmoidal networks: In this exercise we show that there is a graph

(V, Z) such that

he VC dimension of the class of neural networks over these

graphs with the sigmoid activation function is 0(|E|?). Note that for every € >

0, the sigmoid activation function can approximate the threshold activation

function, ly, »,]

, up to accuracy e. To simplify the presentation, throughout

the exercise we assume that we can exactly implement the activation function

lis, 2: >0) using a sigmoid activation function.

Fix some n.

1. Construct a network, Nj, with O(n) weights, which implements a function

from R to {0, 1}” and satisfies the following property. For every x € {0,1}”,

3. Prove Theorem 20.7.

20.9 Exercises 283

if we feed the network with the real number 0.2,272...2n, then the output

of the network will be x.

Hint: Denote a = 0.412%2...2,, and observe that 10*a — 0.5 is at least 0.5

if a, = 1 and is at most —0.3 if x, = —1.

2. Construct a network, No, with O(n) weights, which implements a function

from [n] to {0,1}" such that No(i) = e; for al

i. That is, upon receiving

the input 7, the network outputs the vector of all zeros except 1 at the i’th

neuron.
3. Let ay,
G struc
3 © {0,1}. Construc

plements a function from [n’

)

with a a network, N3, wi

..,Q@y, be n real numbers such that every a; is of the form 0.a

h O(n) weights, which im-

to R, and satisfies No(i) = a; for every i € [n].

4. Combine Nj, N3 to obtain a network that receives i € [n] and output a,

5. Construct a network Ny, that receives (i,j) € [n] x [n] and outputs al.

Hint: Observe that the AND function over {0,
O(1) weights.

}? can be calculated using

6. Conclude that there is a graph with O(n) weights such that the VC di-

mension of the resulting hypothesis class is n?.

Hint: The proof is similar to
paces — see Exercise 32 in Chapter 8.

he hardness of learning intersections of halfs-

(QQ,


Part Ill

Additional Learning Models


21

Online Learning

In this chapter we describe a different model of learning, which is called online
earning. Previously, we studied the PAC learning model, in which the learner
first receives a batch of training examples, uses the training set to learn a hy-
pothesis

and only when learning is completed uses the learned hypothesis for

predicting the label of new examples. In our papayas learning problem, this
means that we should first buy a bunch of papayas and taste them all. Then, we
use all of this information to learn a prediction rule that determines the taste
of new papayas. In contrast, in online learning there is no separation between a
raining phase and a prediction phase. Instead, each time we buy a papaya, it
is first considered a test example since we should predict whether it is going to

aste good. Then, after taking a bite from the papaya, we know the true label,
and the same papaya can be used as a training example that can help us improve
our prediction mechanism for future papayas.

Concretely, online learning takes place in a sequence of consecutive rounds.
On each online round, the learner first receives an instance (the learner buys
a papaya and knows its shape and color, which form the instance). Then, the
earner is required to predict a label (is the papaya tasty?). At the end of the
round, the learner obtains the correct label (he tastes the papaya and then knows
whether it is tasty or not). Finally, the learner uses this information to improve
his future predictions.

To analyze online learning, we follow a similar route to our study of PAC
earning. We start with online binary classification problems. We consider both
he realizable case, in which we assume, as prior knowledge, that all the labels are

generated by some hypothesis from a given hypothesis class, and the unrealizable
case, which corresponds to the agnostic PAC learning model. In particular, we

present an important algorithm called Weighted-Majority. Next, we study online

earning problems in which the loss function is convex. Finally, we present the
Perceptron algorithm as an example of the use of surrogate convex loss functions
in the online learning model.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

288

21.1

Online Learning

Online Classification in the Realizable Case

Online learning is performed in a sequence of consecutive rounds, where at round
t the learner is given an instance, x;, taken from an instance domain 4, and is
required to provide its label. We denote the predicted label by p;. After predicting
the label, the correct label, y, € {0,1}, is revealed to the learner. The learner’s
goal is to make as few prediction mistakes as possible during this process. The
learner tries to deduce information from previous rounds so as to improve its
predictions on future rounds.
Clearly, learning is hopeless if there is no correlation between past and present
rounds. Previously in the book, we studied the PAC model in which we assume
that past and present examples are sampled i.i.d. from the same distribution
source. In the online learning model we make no statistical assumptions regard-

ing the origin of the sequence of examples. The sequence is allowed to be deter-
ministic, stochastic, or even adversarially adaptive to the learner’s own behavior

(as in the case of spam e-mail filtering). Naturally, an adversary can make the

number of prediction mistakes of our online learning algorithm arbitrarily large.

For example, the adversary can present the same instance on each online round,

wait for the learner’s prediction, and provide the opposite label as the correct
label.

To make nontrivial statements we must further restrict the problem. The real-
izability assumption is one possible natural restriction. In the realizable case, we
assume that all the labels are generated by some hypothesis, h* : 4 —> Y. Fur-
thermore, h* is taken from a hypothesis class H, which is known to the learner.
This is analogous to the PAC learning model we studied in Chapter 3. With this
restriction on the sequence, the learner should make as few mistakes as possible,

assuming that both h* and the sequence of instances can be chosen by an ad-

versary. For an online learning algorithm, A, we denote by M4(H) the maximal

number of mistakes A might make on a sequence of examples which is labeled by
some h* € H. We emphasize again that both h* and the sequence of instances
can be chosen by an adversary. A bound on M,4(H) is called a mistake-bound and
we will study how to design algorithms for which M4(H) is minimal. Formally:

DEFINITION 21.1 (Mistake Bounds, Online Learnability) Let H be a hypoth-
esis class and let A be an online learning algorithm. Given any sequence S =
(v1, h*(y1)),..., (a7, h*(yr)), where T is any integer and h* € H, let Ma4(S) be
the number of mistakes A makes on the sequence S. We denote by Ma(H) the

supremum of M4(S)) over all sequences of the above form. A bound of the form
Ma(H) < B < ow is called a mistake bound. We say that a hypothesis class H is
online learnable if there exists an algorithm A for which Ma(H) < B < oo.

Our goal is to study which hypothesis classes are learnable in the online model,
and in particular to find good learning algorithms for a given hypothesis class.

Remark 21.1 Throughout this section and the next, we ignore the computa-

21.1 Online Classification in the Realizable Case 289

tional aspect of learning, and do not restrict the algorithms to be efficient. In
Section 21.3 and Section 21.4 we study efficient online learning algorithms.

To simplify the presentation, we start with the case of a finite hypothesis class,
namely, |H| < co.

In PAC learning, we identified ERM as a good learning algorithm, in the sense
that if H is learnable then it is learnable by the rule ERM. A natural learning
rule for online learning is to use (at any online round) any ERM hypothesis,
namely, any hypothesis which is consistent with all past examples.

Consistent

input: A finite hypothesis class H
initialize: Vj = H
for t=1,2,...
receive X;
choose any h € V;
predict p, = h(x:)
receive true label y; = h* (xz)
update Visa = {hE Vi: h(x) = ye}

The Consistent algorithm maintains a set, V;, of all the hypotheses which
are consistent with (x1, y1),..-,(X—1, yz-1). This set is often called the version

space. It then picks any hypothesis from V; and predicts according to this hy-
pothesis.

Obviously, whenever Consistent makes a prediction mistake, at least one
hypothesis is removed from V;. Therefore, after making M mistakes we have
|\Vi| < |H| — M. Since V;, is always nonempty (by the realizability assumption it
contains h*) we have 1 < |V;| < |H| — M. Rearranging, we obtain the following:

COROLLARY 21.2 LetH be a finite hypothesis class. The Consistent algorithm
enjoys the mistake bound Mconsistent(H) < |H| — 1.

It is rather easy to construct a hypothesis class and a sequence of examples on
which Consistent will indeed make |H|—1 mistakes (see Exercise 1). Therefore,
we present a better algorithm in which we choose h € V; in a smarter way. We
shall see that this algorithm is guaranteed to make exponentially fewer mistakes.

Halving

input: A finite hypothesis class H
initialize: V; = H
for t=1,2,...
receive X;
predict p, = argmax,cyo.1} |{h € Vi: h(x:) = 7}|
(in case of a tie predict p, = 1)
receive true label y, = h* (xz)
update Vivi = {hE Vi: h(x) = yx}


290

21.1.1

Online Learning

THEOREM 21.3 Let H be a finite hypothesis class. The Halving algorithm
enjoys the mistake bound Muawing(H) < logs(|H|).

Proof We simply note that whenever the algorithm errs we have |Vi41| < |Vi|/2,
(hence the name Halving). Therefore, if M is the total number of mistakes, we
have

<|Vryi| < Hl2-™.

Rearranging this inequality we conclude our proof.

Of course, Halving’s mistake bound is much better than Consistent’s mistake
bound. We already see that online learning is different from PAC learning—while
in PAC, any ERM hypothesis is good, in online learning choosing an arbitrary
ERM hypothesis is far from being optimal.

Online Learnability

We next take a more general approach, and aim at characterizing online learn-
ability. In particular, we target the following question: What is the optimal online
class H?

ses that characterizes the best achiev-

learning algorithm for a given hypothesi

We present a dimension of hypothesis
able mistake bound. This measure was proposed by Nick Littlestone and we
therefore refer to it as Ldim(H).

To motivate the definition of Ldim it is convenient to view the online learning
process as a game between two players: the learner versus the environment. On
round t of the game, the environment picks an instance x;, the learner predicts a
label p, € {0,1}, and finally the environment outputs the true label, y, € {0,1}.
Suppose that the environment wants to make the learner err on the first T rounds

of the game. Then, it must output y, = 1 — p;, and the only question is how it
should choose the instances x; in such a way that ensures that for some h* € H
we have y; = h*(x;) for all t € [T].

A strategy for an adversarial environment can be formally described as a
binary tree, as follows. Each node of the tree is associated with an instance from
X. Initially, the environment presents to the learner the instance associated with
the root of the tree. Then, if the learner predicts p, = 1 the environment will
declare that this is a wrong prediction (i.e., y, = 0) and will traverse to the right

child of the current node. If the learner predicts p, = 0 then the environment
will set y, = 1 and will traverse to the left child. This process will continue and
at each round, the environment will present the instance associated with the
current node.

Formally, consider a complete binary tree of depth T (we define the depth of

the tree as the number of edges in a path from the root to a leaf). We have
27+! _ 1 nodes in such a tree, and we attach an instance to each node. Let

Vi,...,V2T+1_1 be these instances. We start from the root of the tree, and set

X1 = vj. At round t, we set x; = v;, where i; is the current node. At the end of

21.1 Online Classification in the Realizable Case 291

hi ho hg ha

vi (O 0 1 1
v2 0 1 * *
, V3 * * 0 1

'
e @

Figure 21.1 An illustration of a shattered tree of depth 2. The dashed path
corresponds to the sequence of examples ((v1, 1), (v3,0)). The tree is shattered by
H = {hi,h2,h3,ha}, where the predictions of each hypothesis in H on the instances
Vi, V2, V3 is given in the table (the ’*’ mark means that hj(vi) can be either 1 or 0).

round t, we go to the left child of i, if y, = 0 or to the right child if y, = 1. That

is, 4441 = 2¢,+y,. Unraveling the recursion we obtain i, = 2'~1 + yj 2s,
The preceding strategy for the environment succeeds only if for every (y1,---, yr)

there exists h € H such that y, = h(x;,) for all t € [T]. This leads to the following

definition.

DEFINITION 21.4 (H Shattered Tree) A shattered tree of depth d is a sequence
of instances v1,...,V2¢_1 in ¥ such that for every labeling (y1,..., ya) € {0, 1}¢

there exists h € H such that for all t € [d] we have h(vi,) = y, where ij =
yates ya,

An illustration of a shattered tree of depth 2 is given in Figure 21.1.

DEFINITION 21.5 (Littlestone’s Dimension (Ldim)) Ldim(H) is the maximal
integer T such that there exists a shattered tree of depth T, which is shattered
by H.

The definition of Ldim and the discussion above immediately imply the fol-
lowing:

LEMMA 21.6 No algorithm can have a mistake bound strictly smaller than
Ldim(H); namely, for every algorithm, A, we have Ma(H) > Ldim(H).

Proof Let T = Ldim(H) and let vi,...,ver_ 1 be a sequence that satisfies the
requirements in the definition of Ldim. If the environment sets x, = vj, an
ye = 1—p, for allt € [T], then the learner makes T mistakes while the definition
of Ldim implies that there exists a hypothesis h € H such that y, = h(x;) for all
t.

Let us now give several examples.

Example 21.2 Let H be a finite hypothesis class. Clearly, any tree that is shat-
tered by H has depth of at most log)(|H|). Therefore, Ldim(H) < logs(|H|).
Another way to conclude this inequality is by combining Lemma 21.6 with The-

orem 21.3.

Example 21.3 Let ¥ = {1,...,d} and H = {hy,...,ha} where hj(a) = 1 iff

292 Online Learning

x = j. Then, it is easy to show that Ldim(H) = 1 while |H| = d can be arbitrarily
large. Therefore, this example shows that Ldim(H) can be significantly smaller
than log»(|H|).

Example 21.4 Let & = [0,1] and H = {x +> Ip <a) : @ € [0, 1]}; namely, H is
the class of thresholds on the interval [0,1]. Then, Ldim(H) = oo. To see this,

consider the tree

This tree is shattered by H. And, because of the density of the reals, this tree
can be made arbitrarily deep.

Lemma 21.6 states that Ldim(H) lower bounds the mistake bound of any
algorithm. Interestingly, there is a standard algorithm whose mistake bound
matches this lower bound. The algorithm is similar to the Halving algorithm.
Recall that the prediction of Halving is made according to a majority vote of
the hypotheses which are consistent with previous examples. We denoted this
set by V;. Put another way, Halving partitions V; into two sets: V;t = {h eV; :
h(x,) = 1} and V> = {h € Vi : h(x,) = O}. It then predicts according to the
larger of the two groups. The rationale behind this prediction is that whenever
Halving makes a mistake it ends up with |Vi41| < 0.5|V%|.

The optimal algorithm we present in the following uses the same idea, but
instead of predicting according to the larger class, it predicts according to the

class with larger Ldim.

Standard Optimal Algorithm (SOA)

input: A hypothesis class H
initialize: Vj = H
for t=1,2,...
receive X;
for r € {0,1} let ve ={heV,: h(x) =r}
predict p, = argmax,¢ 10,1} Ldim(V;”)
(in case of a tie predict py = 1)
receive true label y
update Viqi = {h EV, : h(xt) = ye}

The following lemma formally establishes the optimality of the preceding al-
gorithm.

21.1 Online Classification in the Realizable Case 293

LEMMA 21.7 SOA enjoys the mistake bound Mso4(H) < Ldim(H).

Proof It suffices to prove that whenever the algorithm makes a prediction mis-
take we have Ldim(V;1) < Ldim(V;) — 1. We prove this claim by assuming the
contrary, that is, Ldim(V,,1) = Ldim(V;). If this holds true, then the definition
of p; implies that Ldim(V,"?) = Ldim(V;) for both r = 1 and r = 0. But, then
we can construct a shaterred tree of depth Ldim(V;) + 1 for the class V,, which

leads to the desired contradiction.

Combining Lemma 21.7 and Lemma 21.6 we obtain:

COROLLARY 21.8 Let H be any hypothesis class. Then, the standard optimal
algorithm enjoys the mistake bound Mgoa(H) = Ldim(H) and no other algorithm
can have Ma(H) < Ldim(H).

Comparison to VC Dimension

In the PAC learning model, learnability is characterized by the VC dimension of
the class H. Recall that the VC dimension of a class H is the maximal number
d such that there are instances x),...,Xq that are shattered by H. That is, for

any sequence of labels (yi,-.., ya) € {0,1}% there exists a hypothesis h € H

that gives exactly this sequence of labels. The following theorem relates the VC
dimension to the Littlestone dimension.

THEOREM 21.9 For any class H, VCdim(H) < Ldim(H), and there are classes
for which strict inequality holds. Furthermore, the gap can be arbitrarily larger.

Proof We first prove that VCdim(H) < Ldim(H). Suppose VCdim(H) = d and
let x1,...,Xq be a shattered set. We now construct a complete binary tree of

instances vj,..., Voa_ 1, where all nodes at depth 7 are set to be x; — see the

following illustration:

Now, the definition of a shattered set clearly implies that we got a valid shattere
tree of depth d, and we conclude that VCdim(H) < Ldim(H). To show that the
gap can be arbitrarily large simply note that the class given in Example 21.4 has

VC dimension of 1 whereas its Littlestone dimension is infinite.


294

21.2

Online Learning

Online Classification in the Unrealizable Case

In the previous section we studied online

earnability in the realizable case. We

now consider the unrealizable case. Similarly to the agnostic PAC model, we

no longer assume that all labels are generated by some h* € H, bu
the learner to be competitive with the

captured by the regret of the algorithm,
is, in retrospect, not to have

we require
est fixed predictor from H. This is

which measures how “sorry” the learner

followed the predictions of some hypothesis h € H.

Formally, the regret of an algorithm A relative to h when running on a sequence

of T examples is defined as

Regret 4(h, T) = sup

(141) -(@ryr) [yay

and the regret of the algorithm relative

Regret 4(H, T) = sup Regret 4(h, T).

T Tv 7
Vile = uel — Slr) — wl], (L.A)
t=1 J
to a hypothesis class H is
(21.2)

hEeH

We restate the learner’s goal as having

he lowest possible regret relative to H.

An interesting question is whether we can derive an algorithm with low regret,

meaning that Regret 4(H,T) grows sublinearly with the number of rounds, T,

which implies that the difference between the error rate of

best hypothesis in H tends to zero as T
We first show that this is an impossi
sublinear regret bound even if |H| = 2.
is the
1. An adversary can make the number

equal to T, by simply waiting for the
the op
Yi,--+,yT, let b be the majority of la

mistakes of hy is at most T/2. Therefore, the regre

might be at least T—T/2 = T/2, which
result is attributed to Cover (Cover 196

To sidestep Cover’s impossibility result, we must
of the adversarial environment. We do so by allowing the

his predictions. Of course, this by itself

function that always returns 0 and h, is the function

he learner and the
goes to infinity.
ble mission—no algorithm can obtain a
ndeed, consider H = {ho, hi}, where ho
hat always returns
of mistakes of any online algorithm be
earner’s prediction and then providing

osite label as the true label. In contrast, for any sequence of true labels,

bels in y1,...,yr, then the number of
of any online algorithm
is not sublinear in T. This impossibility

5).

‘urther restrict the power
earner to randomize
does not circumvent Cover’s impossibil-

ity result, since in deriving this result we assumed nothing about the learner’s

strategy.

To make the randomization meaningful, we force

he adversarial envir-

onment to decide on y, without knowing the random coins flipped by the learner

on round t. The adversary can still know the learner’s forecasting strategy and

even the random coin flips of previous rounds, but it does not know the actual

value of the random coin flips used by the learner on round t. With this (mild)

change of game, we analyze the expected number of mistakes of the algorithm,

where the expectation is with respect to the learner’s own randomization. That

is, if the learner outputs 9, where P[gj, = 1] = p;, then the expected loss he pays

21.2.1

21.2 Online Classification in the Unrealizable Case 295

on round t is
Pliie A ye] = |pe — yel-

Put another way, instead of having the predictions of the learner being in {0, 1}
we allow them to be in [0, 1], and interpret p; € [0, 1] as the probability to predict
the label 1 on round t.

With this assumption it is possible to derive a low regret algorithm. In partic-
ular, we will prove the following theorem.

THEOREM 21.10 For every hypothesis class H, there exists an algorithm for
online classification, whose predictions come from [0,1], that enjoys the regret
bound

T T
Wh EH, So |pr—yel— D> h(x) ye] < V2 min{log((H) , Ldim(H) log(eT)} T.

t=1 t=1

Furthermore, no algorithm can achieve an expected regret bound smaller than

Q ( /Ldim(#)T) .

We will provide a constructive proof of the upper bound part of the preceding
theorem. The proof of the lower bound part can be found in (Ben-David, Pal, &
Shalev-Shwartz 2009).

The proof of Theorem 21.10 relies on the Weighted-Majority algorithm for
learning with expert advice. This algorithm is important by itself and we dedicate
the next subsection to it.

Weighted-Majority

Weighted-majority is an algorithm for the problem of prediction with expert ad-
vice. In this online learning problem, on round ¢ the learner has to choose the
advice of d given experts. We also allow the learner to randomize his choice by
defining a distribution over the d experts, that is, picking a vector w € (0, qt,
with 0; wl = 1, and choosing the ith expert with probability wl, After the
learner chooses an expert, it receives a vector of costs, vz € (0, qe, where vj
is the cost of following the advice of the ith expert. If the learner’s predic-
tions are randomized, then its loss is defined to be the averaged cost, namely,
y: wove = (wv). The algorithm assumes that the number of rounds T is
given. In Exercise 4 we show how to get rid of this dependence using the doubling
trick.

296 Online Learning

Weighted-Majority

input: number of experts, d ; number of rounds, T
parameter: 7 = \/2 log(d)/T
initialize: w') = (1,...,1)
for t=1,2,...
set w\) = w' /Z, where Z; = yy, a

choose expert i at random according to P[i] = w
}¢

(t)

i
receive costs of all experts v; € [0,1
pay cost (w“), v,)

update rule Vi, wer?) = DBM ern.

a

The following theorem is key for analyzing the regret bound of Weighted-
Majority.

THEOREM 21.11 Assuming that T > 2log(d), the Weighted-Majority algo-
rithm enjoys the bound

T T
Sow, wi) - min) | Ui < V2 log(d) T.
ie(d]

t=1

Proof We have:

Zin oO , t) —nue
log Z, log de Zi, eee tos youn Mt |

i

Using the inequality e~* < 1— a+ a?/2, which holds for all a € (0,1), and the
fact that >; w = 1, we obtain

Z,
log z < ton Dow” (1 = nui + 1? vz ;/2)

= log(1 — Ss wh? (nvr — nv; ;/2)).

a

def
=b

Next, note that b € (0,1). Therefore, taking log of the two sides of the inequality
1—b<e7» we obtain the inequality log(1 — b) < —b, which holds for all b < 1,

and obtain
log Zi <- Soul? (nut i ve /2)
Zo oe , .
= —n (wv) +1? » wv? ,/2
i
<-n (w, vi) + n?/2.

21.2 Online Classification in the Unrealizable Case 297

Summing this inequality over t we get
2

T T

Z, T

log(Zr41) — log(Z1) = log Zz <-n (wv,) + SS. (21.3)
t=1 t=1

Next, we lower bound Z7+,. For each i, we can rewrite wrt) =e 7st and
we get that

log Zp41 = log (= ene ~) > log (max en Een) =-n mind Ub ie

i
Combining the preceding with Equation (21.3) and using the fact that log(Z1) =
log(d) we get that
T Tr
—1 min)? uti —log(d) < — n> (w,vi) ty
t t=1
which can be rearranged as follows:
a log(d) , nT
Dd (wov) -_ mind Ui < TT + >

Plugging the value of 7 into the equation concludes our proof.

Proof of Theorem 21.10

Equipped with the Weighted-Majority algorithm and Theorem 21.11, we are
ready to prove Theorem 21.10. We start with the simpler case, in which H is
a finite class, and let us write H = {hy,...,hq}. In this case, we can refer to
each hypothesis, h;, as an expert, whose advice is to predict h;(x,), and whose
cost is v,; = |hi(x.) — %|. The prediction of the algorithm will therefore be
mBm=d; whi (x:) € [0,1], and the loss is

d

Ss wo hs(x:) —uU

i=l

d

Ss wl? (hi(xt) —y)).

i=1

|pe — Yel =

Now, if y = 1, then for all 7, hi(x-) — ys < 0. Therefore, the above equals to
y: we? |i (xt) — yz|- If ye = 0 then for all i, hi(xz) — yx > 0, and the above also
equals 57; we? |i (xt) —y,|. All in all, we have shown that

d

Ie — yel = Sw! |i) — ye] = (wv).
i=l

Furthermore, for each i, 5+, vz,; is exactly the number of mistakes hypothesis h;
makes. Applying Theorem 21.11 we obtain

298

Online Learning

COROLLARY 21.12 Let H be a finite hypothesis class. There exists an algorithm
for online classification, whose predictions come from [0, 1], that enjoys the regret
bound

T T
Do peel — pip Dimes) — el Sv? loatlAA) T.

Next, we consider the case of a general hypothesis class. Previously, we con-
structed an expert for each individual hypothesis. However, if H is infinite this
leads to a vacuous bound. The main idea is to construct a set of experts in a
more sophisticated way. The challenge is how to define a set of experts that, on
one hand, is not excessively large and, on the other hand, contains experts that
give accurate predictions.

We construct the set of experts so that for each hypothesis h € H and every
sequence of instances, x1, X2,...,x7, there exists at least one expert in the set
which behaves exactly as h on these instances. For each L < Ldim(#) and each
sequence 1 < iy < ig <-+-- < iz < T we define an expert. The expert simulates
the game between SOA (presented in the previous section) and the environment
on the sequence of instances x1, X9,..., xr assuming that SOA makes a mistake

precisely in rounds 71, i2,...,i2. The expert is defined by the following algorithm.

Expert(i1,i2,..., iz)

input A hypothesis class H ; Indices i, < ig <--: < iz
initialize: V; = H
for t=1,2,...,T7
receive X;
for r € {0,1} let VP = {he Vi: h(x) =r}
define y = argmax,. Ldim (vi)
(in case of a tie set % = 0)
if t é {is,i2,...,ir}
predict y% =1—%%
else
predict % = He
update Vi4i = veo)

Note that each such expert can give us predictions at every round t while only
observing the instances x1,...,x,;. Our generic online learning algorithm is now
an application of the Weighted-Majority algorithm with these experts.

To analyze the algorithm we first note that the number of experts is

Ldim(H)

d= (7). (21.4)

L=0

It can be shown that when T > Ldim(#) +2, the right-hand side of the equation
is bounded by (eT /Ldim(H)) "4" (the proof can be found in Lemma A.5).

21.2 Online Classification in the Unrealizable Case 299

Theorem 21.11 tells us that the expected number of mistakes of Weighted-Majority
is at most the number of mistakes of the best expert plus \/2log(d) T. We will
next show that the number of mistakes of the best expert is at most the number
of mistakes of the best hypothesis in . The following key lemma shows that,
on any sequence of instances, for each hypothesis h € H there exists an expert
with the same behavior.

LEMMA 21.13 Let H be any hypothesis class with Ldim(H) < oo. Let xi,X2,..., xT
be any sequence of instances. For any h € H, there exists L < Ldim(H) and in-
dices 1 <i, <ig < +++ <i, <T such that when running Expert(i1,i2,..., iL)
on the sequence X;,X2,...,x7, the expert predicts h(x,) on each online round
t=1,2,...,T.

Proof Fix h € H and the sequence x1, X2,...,x7. We must construct LZ and the
indices 71, i2,..., iz. Consider running SOA on the input (x1, h(x1)), (x2, h(x2)),
. ++, (&r, h(xr)). SOA makes at most Ldim(H) mistakes on such input. We define
L to be the number of mistakes made by SOA and we define {i1,i2,...,iz} to
be the set of rounds in which SOA made the mistakes.

Now, consider the Expert(i1, i2,..., iz) running on the sequence x1, X2,..., xr.
By construction, the set V; maintained by Expert(i1,i2,...,iz) equals the set V;
maintained by SOA when running on the sequence (x1, h(x1)),..., (xr, h(xr)).
The predictions of SOA differ from the predictions of h if and only if the round is
in {i1,i2,...,iz}. Since Expert(t1, i2,...,iz) predicts exactly like SOA if t is not
in {i1,72,...,2,} and the opposite of SOAs’ predictions if t is in {i1,%2,..., ir},
we conclude that the predictions of the expert are always the same as the pre-
dictions of h.

The previous lemma holds in particular for the hypothesis in that makes the

least number of mistakes on the sequence of examples, and we therefore obtain
the following:

COROLLARY 21.14 Let (x1, 1), (2, y2),---, (Xr, yr) be a sequence of examples
and let H be a hypothesis class with Ldim(H) < oo. There exists L < Ldim(H)
and indices 1 < i) < ig <+++ <i, < T, such that Expert(iy,i2,...,i,) makes

at most as many mistakes as the best h © H does, namely,

T
min h(x) — uel

mistakes on the sequence of examples.

Together with Theorem 21.11, the upper bound part of Theorem 21.10 is
proven.

300

21.3

Online Learning

Online Convex Optimization

In Chapter 12 we studied convex learning problems and showed learnability
results for these problems in the agnostic PAC learning framework. In this section
we show that similar learnability results hold for convex problems in the online
learning framework. In particular, we consider the following problem.

Online Convex Optimization

definitions:

hypothesis class H ; domain Z ; loss function :HxZ— oR
assumptions:

H is convex

Vz € Z, &(-,z) is a convex function
for t=1,2,...,T

learner predicts a vector w\) € H

environment responds with z € Z

learner suffers loss ¢(w“), 24)

As in the online classification problem, we analyze the regret of the algorithm.

Recall that the regret of an online algorithm with respect to a competing hy-
pothesis, which here will be some vector w* € H, is defined as

T T
Regret 4(w*,T) = So ew, 2) — So ew", 21). (21.5)
t=1 t=1
As before, the regret of the algorithm relative to a set of competing vectors, H,
is defined as
Regret 4(H,T) = sup Regret 4(w*,T).
w*cH
In Chapter 14 we have shown that Stochastic Gradient Descent solves convex
learning problems in the agnostic PAC model. We now show that a very similar
algorithm, Online Gradient Descent, solves online convex learning problems.

Online Gradient Descent

parameter: 7) > 0
initialize: w‘) =0

predict w'?)
receive z and let fi(-) = C(-, ze)
choose v; € Of;(w)
update:
1 wd) = wl — ny,
2. wet) = argmin,, cy ||w — w't2) |


21.4

21.4 The Online Perceptron Algorithm 301

THEOREM 21.15 The Online Gradient Descent algorithm enjoys the following
regret bound for every w* € H,

Regret 4(w*,T) <

If we further assume that fy, is prs for allt, then setting n =1/VT yields
Regret 4(w*,T) < = x (lbw? + p)vT.
If we further assume that H is B-bounded and we set n = WE then

Regret 4(H,T) < BpvT.

Proof The analysis is similar to the analysis of Stochastic Gradient Descent
with projections. Using the projection lemma, the definition of wltt3), and the
definition of subgradients, we have that for every t,

42) — w= Iw — wr
= |Iw JD — w+ wD — wr? = fw — wf?

< |]w2) — we" |]? — jw! — we |?

(t+1) _ w* ||? _

= ||w — nv, — w* ||? = lw — w* |)?
= =2n(w) — w*,vi) + 9? llvell?
—2n(felw) — fu(w*)) + 1? Ive l]?.

Summing over ¢ and observing that the left-hand side is a telescopic sum we
obtain that

IA

T T
IjwP HD — wr |]? = lw — wi? < —2n SO (felw') = few*)) +7? D2 |hvell?.
t=1

t=1

Rearranging the inequality and using the fact that w“) = 0, we get that

T

2

+5 Do livell?
t=1

T \jw) _ w* ||? _ jw) _ w* |?

Di(fe(w) = filw*)) < on

t=1
T
=> Ilva).

This proves the first bound in the theorem. The second bound follows from the

cers

‘sts

assumption that f; is p-Lipschitz, which implies that ||v:|| <p.

The Online Perceptron Algorithm

The Perceptron is a classic online learning algorithm for binary classification with
the hypothesis class of homogenous halfspaces, namely, H = {x ++ sign((w,x)) :

302

Online Learning

w € R“}. In Section 9.1.2 we have presented the batch version of the Perceptron,
which aims to solve the ERM problem with respect to H. We now present an
online version of the Perceptron algorithm.

Let ¥ = R14, Y= {1,1}. On round t, the learner receives a vector x; € R¢.
The learner maintains a weight vector w“) € R@ and predicts p, = sign((w“), x,)).
Then, it receives y, € Y and pays 1 if p, 4 y, and 0 otherwise.

The goal of the learner is to make as few prediction mistakes as possible. In
Section 21.1 we characterized the optimal algorithm and showed that the best:

achievable mistake bound depends on the Littlestone dimension of the class.
We show later that if d > 2 then Ldim(H) = 00, which implies that we have
no hope of making few prediction mistakes. Indeed, consider the tree for which
v= (5. 1,0,...,0), vo = (4. 1,0,...,0), vg = (3, 1,0,...,0), ete. Because of
the density of the reals, this tree is shattered by the subset of H which contains

all hypotheses that are parametrized by w of the form w = (—1,a,0,...,0), for
a € [0,1]. We conclude that indeed Ldim(H) = co.
To sidestep this impossibility result, the Perceptron algorithm relies on the

technique of surrogate convex losses (see Section 12.3). This is also closely related
to the notion of margin we studied in Chapter 15.
A weight vector w makes a mistake on an example (x, y) whenever the sign of

(w, x) does not equal y. Therefore, we can write the 0—1 loss function as follows

E(w, (x, 9)) = Yyiwx) <0):
On rounds on which the algorithm makes a prediction mistake, we shall use the
hinge-loss as a surrogate convex loss function
fi(w) = max{0, 1 — ys: (w, xz) }.
The hinge-loss satisfies the two conditions:

e f; is a convex function
e For all w, f,(w) > €(w, (x;, y))- In particular, this holds for w™.

On rounds on which the algorithm is correct, we shall define f,;(w) = 0. Clearly,
fi; is convex in this case as well. Furthermore, f;(w) = ¢(w™, (xt, yz) = 0.
Remark 21.5 In Section 12.3 we used the same surrogate loss function for all the
examples. In the online model, we allow the surrogate to depend on the specific
round. It can even depend on w"). Our ability to use a round specific surrogate
stems from the worst-case type of analysis we employ in online learning.

Let us now run the Online Gradient Descent algorithm on the sequence of
functions, fi,..., fr, with the hypothesis class being all vectors in R? (hence,
the projection step is vacuous). Recall that the algorithm initializes w“) = 0
and its update rule is

wht) = w — ny,

for some v, € Of;(w). In our case, if y:(w,x,) > 0 then f;, is the zero

21.4 The Online Perceptron Algorithm 303

function and we can take v; = 0. Otherwise, it is easy to verify that vi = —y:xt
is in Of;(w™). We therefore obtain the update rule

with) — wi!) if y(w, xt) > 0
w) + ny:x, otherwise

Denote by M the set of rounds in which sign((w“),x;)) 4 yz. Note that on
round t, the prediction of the Perceptron can be rewritten as

pr = sign((w,x,)) = sign (» i xm)

tEeMii<t

This form implies that the predictions of the Perceptron algorithm and the set
M do not depend on the actual value of 7 as long as 7 > 0. We have therefore
obtained the Perceptron algorithm:

Perceptron

initialize: w,; =0
for t=1,2,...,T
receive X;
predict p, = sign((w“), x;))
if y(w, x) <0
wt) = wl) + yx,
else
wit) = wl)

To analyze the Perceptron, we rely on the analysis of Online Gradient De-
scent given in the previous section. In our case, the subgradient of f; we use
in the Perceptron is vz = —Lhy (w xt) <0] yt Xt. Indeed, the Perceptron’s update
is wet) = w) — v,, and as discussed before this is equivalent to w¢t) =
w'') — nv; for every 7 > 0. Therefore, Theorem 21.15 tells us that

T T 1 1” Tv
DY few) — $7 fiw*) < aq Wl +5 do livell2-
t=1 t=1 t=1

Since f;(w) is a surrogate for the 0—1 loss we know that a filw) > |MI.
Denote R = max; ||x;||; then we obtain

T
lay) < ty 4 2
[M| — D7 fils") <5 llw' ls + 51M Re
t=1

Iw" |]

Setting 7 = RVI and rearranging, we obtain

T
M| — Riw* || VIM — SO filw*) <0. (21.6)
t=1

This inequality implies

304

21.5

Online Learning

THEOREM 21.16 Suppose that the Perceptron algorithm runs on a sequence
(x1,41),-.-,(&r.yr) and let R = max; ||x;||. Let M be the rounds on which the
Perceptron errs and let fi(w) = teem [1 — ye(w,xe)|,. Then, for every w*

IM < D0 felw*) + Riw* ||, [D0 few) +R? ||we |?

In particular, if there exists w* such that y,(w*,x,) > 1 for allt then
|M| < R? ||w*|)?.

Proof The theorem follows from Equation (21.6) and the following claim: Given
x,b,c € Ry, the inequality 2 — b\/z —c < 0 implies that « < c+? +b Ve. The
last claim can be easily derived by analyzing the roots of the convex parabola
Qy) =y? — by -e.

The last assumption of Theorem 21.16 is called separability with large margin
(see Chapter 15). That is, there exists w* that not only satisfies that the point
x; lies on the correct side of the halfspace, it also guarantees that x; is not too
close to the decision boundary. More specifically, the distance from x; to the
decision boundary is at least y = 1/||w*|| and the bound becomes (R/7)?.

When the separability assumption does not hold, the bound involves the term
[1 — yx(w*,x)], which measures how much the separability with margin require-
ment is violated.

As a last remark we note that there can be cases in which there exists some
w* that makes zero errors on the sequence but the Perceptron will make many
errors. Indeed, this is a direct consequence of the fact that Ldim(H) = oo. The
way we sidestep this impossibility result is by assuming more on the sequence of
examples — the bound in Theorem 21.16 will be meaningful only if the cumulative
surrogate loss, }>, f;(w*) is not excessively large.

Summary

In this chapter we have studied the online learning model. Many of the results
we derived for the PAC learning model have an analog in the online model. First,
we have shown that a combinatorial dimension, the Littlestone dimension, char-
acterizes online learnability. To show this, we introduced the SOA algorithm (for
the realizable case) and the Weighted-Majority algorithm (for the unrealizable
case). We have also studied online convex optimization and have shown that
online gradient descent is a successful online learner whenever the loss function
is convex and Lipschitz. Finally, we presented the online Perceptron algorithm
as a combination of online gradient descent and the concept of surrogate convex

loss functions.

21.6

21.7

21.6 Bibliographic Remarks 305

Bibliographic Remarks

The Standard Optimal Algorithm was derived by the seminal work of Lit-
tlestone (1988). A generalization to the nonrealizable case, as well as other
variants like margin-based Littlestone’s dimension, were derived in (Ben-David
et al. 2009). Characterizations of online learnability beyond classification have
been obtained in (Abernethy, Bartlett, Rakhlin & Tewari 2008, Rakhlin, Srid-
haran & Tewari 2010, Daniely et al. 2011). The Weighted-Majority algorithm is
due to (Littlestone & Warmuth 1994) and (Vovk 1990).

The term “online convex programming” was introduced by Zinkevich (2003)
but this setting was introduced some years earlier by Gordon (1999). The Per-
ceptron dates back to Rosenblatt (Rosenblatt 1958). An analysis for the re-
alizable case (with margin assumptions) appears in (Agmon 1954, Minsky &
Papert 1969). Freund and Schapire (Freund & Schapire 1999) presented an anal-
ysis for the unrealizable case with a squared-hinge-loss based on a reduction to

the realizable case. A direct analysis for the unrealizable case with the hinge-loss
was given by Gentile (Gentile 2003).

For additional information we refer the reader to Cesa-Bianchi & Lugosi (2006)
and Shalev-Shwartz (2011).

Exercises

1. Find a hypothesis class H and a sequence of examples on which Consistent
makes |H| — 1 mistakes.
2. Find a hypothesis class H and a sequence of examples on which the mistake
bound of the Halving algorithm is tight.
3. Let d> 2, X = {1,...,d} and let H = {hj : 7 € [d]}, where hj(x) = I,—5-
Calculate Muaiving(H) (i.e., derive lower and upper bounds on Myaiving(H),
and prove that they are equal).

4. The Doubling Trick:
In Theorem 21.15, the parameter 7 depends on the time horizon T. In this

exercise we show how to get rid of this dependence by a simple trick.

Consider an algorithm that enjoys a regret bound of the form aVT, but
its parameters require the knowledge of T. The doubling trick, described in
the following, enables us to convert such an algorithm into an algorithm that
does not need to know the time horizon. The idea is to divide the time into
periods of increasing size and run the original algorithm on each period.

The Doubling Trick

input: algorithm A whose parameters depend on the time horizon
for m= 0,1,2,...
run A on the 2” rounds t = 2”",..., gmt y


306

Online Learning

Show that if the regret of A on each period of 2 rounds is at most avV2™,
then the total regret is at most

v2
Sov?

. Online-to-batch Conversions: In this exercise we demonstrate how a suc-

cessful online learning algorithm can be used to derive a successful PAC
learner as well.

Consider a PAC learning problem for binary classification parameterized
by an instance domain, 1’, and a hypothesis class, H. Suppose that there exists
an online learning algorithm, A, which enjoys a mistake bound M4(H) < oo.
Consider running this algorithm on a sequence of T examples which are sam-
pled i.i.d. from a distribution D over the instance space 1’, and are labeled by
some h* € H. Suppose that for every round t¢, the prediction of the algorithm
is based on a hypothesis h, : ¥ > {0,1}. Show that
< MalX)
~ TT

where the expectation is over the random choice of the instances as well as a

E[Lo(hr)]

random choice of r according to the uniform distribution over [T].
Hint: Use similar arguments to the ones appearing in the proof of Theo-
rem 14.8.

22 Clustering

Clustering is one of the most widely used techniques for exploratory data anal-
ysis. Across all disciplines, from social sciences to biology to computer science,
people try to get a first intuition about their data by identifying meaningful
groups among the data points. For example, computational biologists cluster
genes on the basis of similarities in their expression in different experiments; re-
ailers cluster customers, on the basis of their customer profiles, for the purpose
of targeted marketing; and astronomers cluster stars on the basis of their spacial
proximity.
The first point that one should clarify is, naturally, what is clustering? In-
uitively, clustering is the task of grouping a set of objects such that similar

objects end up in the same group and dissimilar objects are separated into dif-
ferent groups. Clearly, this description is quite imprecise and possibly ambiguous.
Quite surprisingly, it is not at all clear how to come up with a more rigorous

definition.
There are several sources for this difficulty. One basic problem is that the
wo objectives mentioned in the earlier statement may in many cases contradict

each other. Mathematically speaking, similarity (or proximity) is not a transi-
ive relation, while cluster sharing is an equivalence relation and, in particular,

it is a transitive relation. More concretely, it may be the case that there is a

long sequence of objects, 11,...,2%m such that each 2; is very similar to its two
neighbors, z;~1 and x41, but x; and x, are very dissimilar. If we wish to make
sure that whenever two elements are similar they share the same cluster, then
we must put all of the elements of the sequence in the same cluster. However,

in that case, we end up with dissimilar elements (x; and 2) sharing a cluster,

thus violating the second requirement.
To illustrate this point further, suppose that we would like to cluster the points
in the following picture into two clusters.

A clustering algorithm that emphasizes not separating close-by points (e.g., the
Single Linkage algorithm that will be described in Section 22.1) will cluster this
input by separating it horizontally according to the two lines:

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

308 Clustering

In contrast, a clustering method that emphasizes not having far-away points
share the same cluster (e.g., the 2-means algorithm that will be described in
Section 22.1) will cluster the same input by dividing it vertically into the right-
hand half and the left-hand half:

Another basic problem is the lack of “ground truth” for clustering, which is a
common problem in unsupervised learning. So far in the book, we have mainly
dealt with supervised learning (e.g., the problem of learning a classifier from
abeled training data). The goal of supervised learning is clear — we wish to
earn a classifier which will predict the labels of future examples as accurately
as possible. Furthermore, a supervised learner can estimate the success, or the
risk, of its hypotheses using the labeled training data by computing the empirical
oss. In contrast, clustering is an unsupervised learning problem; namely, there
are no labels that we try to predict. Instead, we wish to organize the data in
some meaningful way. As a result, there is no clear success evaluation procedure
or clustering. In fact, even on the basis of full knowledge of the underlying data
distribution, it is not clear what is the “correct” clustering for that data or how
o evaluate a proposed clustering.

Consider, for example, the following set of points in R?:

and suppose we are required to cluster them into two clusters. We have two
highly justifiable solutions:

Clustering 309

This phenomenon is not just artificial but occurs in real applications. A given
set of objects can be clustered in various different meaningful ways. This may

be due to having different implicit notions of distance (or similarity) between

objects, for example, clustering recordings of speech by the accent of the speaker

versus clustering them by content, clustering movie reviews by movie topic versus

clustering them by the review sentiment, clustering paintings by topic versus

clustering them by style, and so on.

To summarize, there may be several very different conceivable clustering so-

lutions for a given data set. As a result, there is a wide variety of clustering

algorithms that, on some input data, will output very different clusterings.

A Clustering Model:
Clustering tasks can vary in terms of both the type of input they have and the

type of outcome they are expected to compute. For concreteness, we shall focus

on the following common setup:

Input — aset of elements, V, and a distance function over it. That is, a function
d: Xx X — Ry, that is symmetric, satisfies d(x,x) = 0 for all x € ¥
and often also satisfies the triangle inequality. Alternatively, the function

could be a simi
and satisfies s(x, x

arity function s : VY x ¥ — [0,1] that is symmetric

x) = 1 for all a € &. Additionally, some clustering

algorithms also require an input parameter k (determining the number

of require

Output —a part
where L*
clustering

is probabi

point, 7 € V,a

the proba

a clustering den
h is a hierarchical tree of domain subsets, having the singleton

ing), whic

i=l

ition 0:
C; =

is “soft

clusters).

istic w!

the domain set 4 into subsets. That is, C = (C1,... Cx)
& and for alli 4 7, C3:NC; = O. In some situations the
,” namely, the partition of ¥ into the different clusters
here the output is a function assigning to each domain
vector (pi(x),...,pe(x)), where p;(x) = P[x € Cj] is

ility

hat x belongs to cluster C;. Another possible output is

drogram (from Greek dendron = tree, gramma = draw-

sets in its leaves, and the full domain as its root. We shall discuss this

formulation in more detail in the following.

310 Clustering

In the following we survey some of the most popular clustering methods. In
the last section of this chapter we return to the high level discussion of what is
clustering.

22.1 Linkage-Based Clustering Algorithms

Linkage-based clustering is probably the simplest and most straightforward paradigm
of clustering. These algorithms proceed in a sequence of rounds. They start from
the trivial clustering that has each data point as a single-point cluster. Then,
repeatedly, these algorithms merge the “closest” clusters of the previous cluster-
ing. Consequently, the number of clusters decreases with each such round. If kept
going, such algorithms would eventually result in the trivial clustering in which
all of the domain points share one large cluster. Two parameters, then, need to
be determined to define such an algorithm clearly. First, we have to decide how

to measure (or define) the distance between clusters, and, second, we have to

determine when to stop merging. Recall that the input to a clustering algorithm

is a between-points distance function, d. There are many ways of extending d to
a measure of distance between domain subsets (or clusters). The most common
ways are

1. Single Linkage clustering, in which the between-clusters distance is defined
by the minimum distance between members of the two clusters, namely,

de:

D(A, B) ey min{d(x,y):a€ A, y € B}

2. Average Linkage clustering, in which the distance between two clusters is

defined to be the average distance between a point in one of the clusters and
a point in the other, namely,

1
D(A,B) & ——_ d(ax,y
mB 2,

3. Max Linkage clustering, in which the distance between two clusters is defined
as the maximum distance between their elements, namely,

D(A, B) a max{d(x,y): 2 € A, y € B}.

The linkage-based clustering algorithms are agglomerative in the sense that they
start from data that is completely fragmented and keep building larger and
larger clusters as they proceed. Without employing a stopping rule, the outcome
of such an algorithm can be described by a clustering dendrogram: that is, a tree
of domain subsets, having the singleton sets in its leaves, and the full domain as
its root. For example, if the input is the elements ¥ = {a,b,c,d,e} C R? with
the Euclidean distance as depicted on the left, then the resulting dendrogram is
the one depicted on the right:

22.2

22.2 k-Means and Other Cost Minimization Clusterings 311

{a,b,c,d,e}
\
ea {b,c,d,e}
e JoO™
ed {b, c} {d,e}

. /\ /\
e {a} {db} {ec} {a} {e}

The single linkage algorithm is closely related to Kruskal’s algorithm for finding
a minimal spanning tree on a weighted graph. Indeed, consider the full graph
whose vertices are elements of ¥ and the weight of an edge (zx, y) is the distance
d(x,y). Each merge of two clusters performed by the single linkage algorithm
corresponds to a choice of an edge in the aforementioned graph. It is also possible
to show that the set of edges the single linkage algorithm chooses along its run
forms a minimal spanning tree.

If one wishes to turn a dendrogram into a partition of the space (a clustering),
one needs to employ a stopping criterion. Common stopping criteria include

e Fixed number of clusters — fix some parameter, k, and stop merging clusters
as soon as the number of clusters is k.

e Distance upper bound ~ fix some r € R,. Stop merging as soon as all the
between-clusters distances are larger than r. We can also set r to be

,y € X} for some a < 1. In that case the stopping
criterion is called “scaled distance upper bound.”

amax{d(x,y) :

k-Means and Other Cost Minimization Clusterings

Another popular approach to clustering starts by defining a cost function over a
parameterized set of possible clusterings and the goal of the clustering algorithm
is to find a partitioning (clustering) of minimal cost. Under this paradigm, the
clustering task is turned into an optimization problem. The objective function
is a function from pairs of an input, (4’,d), and a proposed clustering solution
C = (C\,...,Cx), to positive real numbers. Given such an objective function,
which we denote by G, the goal of a clustering algorithm is defined as finding, for
a given input (1, d), a clustering C so that G((¥,d),C) is minimized. In order
to reach that goal, one has to apply some appropriate search algorithm.

As it turns out, most of the resulting optimization problems are NP-hard, and

some are even NP-hard to approximate. Consequently, when people talk about,
say, k-means clustering, they often refer to some particular common approxima-

tion algorithm rather than the cost function or the corresponding exact solution
of the minimization problem.

Many common objective functions require the number of clusters, k, as a

312

Clustering

parameter. In practice, it is often up to the user of the clustering algorithm to
choose the parameter k that is most suitable for the given clustering problem.
In the following we describe some of the most common objective functions.

e The k-means objective function is one of the most popular clustering

objectives. In k-means the data is partitioned into disjoint sets C),...,C
where each C; is represented by a centroid j1;. It is assumed that the input
set ¥ is embedded in some larger metric space (¥’,d) (so that ¥ C ¥’)
and centroids are members of ¥’. The k-means objective function measures
the squared distance between each point in ¥ to the centroid of its cluster.
The centroid of C; is defined to be

pi(Ci) = argmin Ss d(a, 1)?

HEX EC;

Then, the k-means objective is

k
Gi—means((¥, 4d), (Ci,.--+Cr)) => dal x, Ui(C,
i=l weC;
This can also be rewritten as

Gimanl D(C) =, i Do A (@, pi). (22.1)

The k-means objective function is relevant, for example, in digital com-
munication tasks, where the members of 4 may be viewed as a collection
of signals that have to be transmitted. While VY may be a very large set
of real valued vectors, digital transmission allows transmitting of only a
finite number of bits for each signal. One way to achieve good transmis-
sion under such constraints is to represent each member of ¥V by a “close”
member of some finite set j1,.../4x, and replace the transmission of any
x € & by transmitting the index of the closest j1;. The k-means objective

can be viewed as a measure of the distortion created by such a transmission
representation scheme.

e The k-medoids objective function is similar to the k-means objective,

except that it requires the cluster centroids to be members of the input
set. The objective function is defined by

Gx_medoia((¥, d), (C1, ---, Cx)) =e min > SS a x, Mi)”

x
MER eC;

e The k-median objective function is quite similar to the k-medoids objec-

tive, except that the “distortion” between a data point and the centroid
of its cluster is measured by distance, rather than by the square of the
distance:

Gk—median((¥,d), (Ci,...,Ck)) = min. BS Ss d(x, 11i)

i=1 c€C;

22.2.1

22.2 k-Means and Other Cost Minimization Clusterings 313

An example where such an objective makes sense is the facility location
problem. Consider the task of locating k fire stations in a city. One can
model houses as data points and aim to place the stations so as to minimize
the average distance between a house and its closest fire station.

The previous examples can all be viewed as center-based objectives. The so-
lution to such a clustering problem is determined by a set of cluster centers,
and the clustering assigns each instance to the center closest to it. More gener-
ally, center-based objective is determined by choosing some monotonic function
f : Ry — Ry and then defining

where 1’ is either Y or some superset of Y.
Some objective functions are not center based. For example, the sum of in-
cluster distances (SOD)

k
Gsov((¥, 4), (C1,.--Cx)) => SO d(w,y)

i=1 2,yeCi

and the MinCut objective that we shall discuss in Section 22.3 are not center-
based objectives.

The k-Means Algorithm

The k-means objective function is quite popular in practical applications of clus-
tering. However, it turns out that finding the optimal k-means solution is of-
ten computationally infeasible (the problem is NP-hard, and even NP-hard to
approximate to within some constant). As an alternative, the following simple
iterative algorithm is often used, so often that, in many cases, the term k-means
Clustering refers to the outcome of this algorithm rather than to the cluster-
ing that minimizes the k-means objective cost. We describe the algorithm with
respect to the Euclidean distance function d(x, y) = ||x — y||.

k-Means

input: ¥ CR” ; Number of clusters k
initialize: Randomly choose initial centroids p4,..., Uy,
repeat until convergence
Vi € [k] set C; = {x € Vs i = argmin, ||x — ||}
(break ties in some arbitrary manner)
Vi € [k] update p, = Tal exec; ¥

LEMMA 22.1 Each iteration of the k-means algorithm does not increase the
k-means objective function (as given in Equation (22.1)).

314 Clustering

Proof To simplify the notation, let us use the shorthand G(C},...,C;,) for the
k-means objective, namely,

G(C,,...,Ck) = min S Ss \|x — p,l|?- (22.2)

i=1 x€Ci

It is convenient to define (C;) = real Ve xec; x and note that (Ci) = argmin,,cpn Vxec;

||?. Therefore, we can rewrite the k-means objective as

k
G1, Cn) = 32 YE |e = H(GAIP. (22.3)

i=1 x€Ci

Consider the update at iteration t of the k-means algorithm. Let ct Do, ce »
be the previous partition, let pd Dx po), and let fone peees cl be the
new partition assigned at iteration t. Using the definition of the objective as

given in Equation (22.2) we clearly have that

k
GCP. CP) SSD SE x OP IP. (22.4)

I=1 yea

In addition, the definition of the new partition (cl, CM) implies that it

1)
Ix — wf P |?

minimizes the expression yt ini Do over all possible partitions

(Ci,...,Cx). Hence,

xeC; |

k k
STS lew PPR SSS SE pe wf P IP. (22.5)

i=l xec!? i=1 xec(")

Using Equation (22.3) we have that the right-hand side of Equation (22.5) equals

acl? pees ct ). Combining this with Equation (22.4) and Equation (22.5),
we obtain that cl. pees Cl) < ac Dy ct ), which concludes our
proof.

While the preceding lemma tells us that the k-means objective is monotonically
nonincreasing, there is no guarantee on the number of iterations the k-means al-

gorithm needs in order to reach convergence. Furthermore, there is no nontrivia
lower bound on the gap between the value of the k-means objective of the al-

gorithm’s output and the minimum possible value of that objective function. In
fact, k-means might converge to a point which is not even a local minimum (see
Exercise 2). To improve the results of k-means it is often recommended to repeat
the procedure several times with different randomly chosen initial centroids (e.g.,
we can choose the initial centroids to be random points from the data).


22.3

22.3.1

22.3.2

22.3 Spectral Clustering 315

Spectral Clustering

Often, a convenient way to represent the relationships between points in a data
set VY = {21,...,2%m} is by a similarity graph; each vertex represents a data
point x;, and every two vertices are connected by an edge whose weight is their
similarity, Wi; = s(xi,2;), where W € R™"". For example, we can set Wi; =
exp(—d(2;,x;)?/o7), where d(-,-) is a distance function and is a parameter.
The clustering problem can now be formulated as follows: We want to find a
partition of the graph such that the edges between different groups have low
weights and the edges within a group have high weights.

In the clustering objectives described previously, the focus was on one side
of our intuitive definition of clustering — making sure that points in the same
cluster are similar. We now present objectives that focus on the other requirement
— points separated into different clusters should be nonsimilar.

Graph Cut

Given a graph represented by a similarity matrix W, the simplest and most
direct way to construct a partition of the graph is to solve the mincut problem,
which chooses a partition C,,...,C, that minimizes the objective

k
cut(Cy,...,Ck) = Ss Ss W,,s-

i=1 r€Ci,s¢Ci

For k = 2, the mincut problem can be solved efficiently. However, in practice it
often does not lead to satisfactory partitions. The problem is that in many cases,
the solution of mincut simply separates one individual vertex from the rest of the
graph. Of course, this is not what we want to achieve in clustering, as clusters
should be reasonably large groups of points.

Several solutions to this problem have been suggested. The simplest solution
is to normalize the cut and define the normalized mincut objective as follows:

k
1
RatioCut(C,...,Ck) = G W,,s-
& IGil reCi,s¢C;

The preceding objective assumes smaller values if the clusters are not too small.
Unfortunately, introducing this balancing makes the problem computationally
hard to solve. Spectral clustering is a way to relax the problem of minimizing
RatioCut.

Graph Laplacian and Relaxed Graph Cuts

The main mathematical object for spectral clustering is the graph Laplacian
matrix. There are several different definitions of graph Laplacian in the literature,
and in the following we describe one particular definition.

316

Clustering

DEFINITION 22.2 (Unnormalized Graph Laplacian) The unnormalized graph
Laplacian is the m x m matrix L = D—W where D is a diagonal matrix with
Di = ea W;,,;. The matrix D is called the degree matriz.

The following lemma underscores the relation between RatioCut and the Lapla-

cian matrix.

LEMMA 22.3. Let Cy,...,Cy be a clustering and let H € R™* be the matrix
such that

1
Hig = Jie lhiec,)-

Then, the columns of H are orthonormal to each other and
RatioCut(C1,...,C) = trace(H' LH).

Proof Let hi,...,h, be the columns of H. The fact that these vectors are
orthonormal is immediate from the definition. Next, by standard algebraic ma-
nipulations, it can be shown that trace(H LH) = 7*_, hj] Lh; and that for
any vector v we have

1 1
vilv= 5 (= Dy..v2 = oe UpUgWrg + e D,.) =35 Ss W,.,5(Up — vs)?-

rs

Applying this with v = h; and noting that (hj, — hi,s)? is nonzero only if
r € Cj, s € C; or the other way around, we obtain that

1
h] Lh; = » Ws.
‘ ICi| a

reECi,s¢Ci

Therefore, to minimize RatioCut we can search for a matrix H whose columns
are orthonormal and such that each H;,; is either 0 or 1/ VIG . Unfortunately,
this is an integer programming problem which we cannot solve efficiently. Instead,
we relax the latter requirement and simply search an orthonormal matrix H €
R™* that minimizes trace(H' LH). As we will see in the next chapter about
PCA (particularly, the proof of Theorem 23.2), the solution to this problem is
to set U to be the matrix whose columns are the eigenvectors corresponding to
the k minimal eigenvalues of L. The resulting algorithm is called Unnormalized

Spectral Clustering.

22.3.3

22.4

Unnormalized Spectral Clusteri

22.4 Information Bottleneck* 317

ng

Cluster the points vi,...
Output: Clusters C1,...,

Unnormalized Spectral Clustering

Input: W € R™™ ; Number of clusters k

Initialize: Compute the unnormalized graph Laplacian L

Let U € R™* be the matrix whose columns are the eigenvectors of L
corresponding to the k smallest eigenvalues

Let vi,...,Vm be the rows of U

+>Vm using k-means
Cx of the k-means algorithm

The spectral clustering algorithm starts with finding the matrix H of the k
eigenvectors corresponding to the smallest eigenvalues of the graph Laplacian

matrix. It then represents point:

s according to the rows of H. It is due to the

properties of the graph Laplacians that this change of representation is useful.

In many situations, this change

of representation enables the simple k-means

algorithm to detect the clusters seamlessly. Intuitively, if H is as defined in

Lemma 22.3 then each point in
whose value is nonzero only on th
to.

Information Bottleneck*
The information bottleneck me

Tishby, Pereira, and Bialek. It
illustrate the method, consider t

the new representation is an indicator vector
e element corresponding to the cluster it belongs

hod is a clustering technique introduced by
relies on notions from information theory. To
he problem of clustering text documents where

each document is represented as a bag-of-words; namely, each document is a

vector x = {0,1}", where n is the size of the dictionary and x; = 1 iff the word

corresponding to index i appears
we can interpret the bag-of-wor

probability over a random variab.
taking values in [m]), and a rand

in the dictionary (thus taking values in [n]).

a clustering as another random
(where k will be set by the met

in the document. Given a set of m documents,
s representation of the m documents as a joint
e x, indicating the identity of a document (thus
om variable y, indicating the identity of a word

With this interpretation, the information bottleneck refers to the identity of

variable, denoted C, that takes values in [k]
hod as well). Once we have formulated x, y,C

as random variables, we can use tools from information theory to express a

clustering objective. In particular, the information bottleneck objective is

min
P(Clx)

I(a;C) — BI(C;y) ,

where I(-;-) is the mutual information between two random variables,! 6 is a

1 That is, given a probability function, p over the pairs (x,C),

318

22.5

Clustering

parameter, and the minimization is over all possible probabilistic assignments of
points to clusters. Intuitively, we would like to achieve two contradictory goals.
On one hand, we would like the mutual information between the identity of
the document and the identity of the cluster to be as small as possible. This
reflects the fact that we would like a strong compression of the original data. On
the other hand, we would like high mutual information between the clustering
variable and the identity of the words, which reflects the goal that the “relevant”
information about the document (as reflected by the words that appear in the
document) is retained. This generalizes the classical notion of minimal sufficient
statistics? used in parametric statistics to arbitrary distributions.

Solving the optimization problem associated with the information bottleneck
principle is hard in the general case. Some of the proposed methods are similar

to the EM principle, which we will discuss in Chapter 24.

A High Level View of Clustering

So far, we have mainly listed various useful clustering tools. However, some fun-
damental questions remain unaddressed. First and foremost, what is clustering?
What is it that distinguishes a clustering algorithm from any arbitrary function
that takes an input space and outputs a partition of that space? Are there any
basic properties of clustering that are independent of any specific algorithm or
task?

One method for addressing such questions is via an axiomatic approach. There
have been several attempts to provide an axiomatic definition of clustering. Let
us demonstrate this approach by presenting the attempt made by Kleinberg
(2003).

Consider a clustering function, F’, that takes as input any finite domain V

with a dissimilarity function d over its pairs and returns a partition of 1.
Consider the following three properties of such a function:

Scale Invariance (SI) For any domain set ¥, dissimilarity function d, and
any a > 0, the following should hold: F(4,d) = F(¥,ad) (where
def
(ad)(a,y) = ad(a,y)).
Richness (Ri) For any finite V and every partition C = (C1,...C,) of X (into
nonempty subsets) there exists some dissimilarity function d over ¥ such

that F(¥,d) =C.

I(a;C) =>, dy pa, b) log (#45), where the sum is over all values x can take and all
values C can take.

2 A sufficient statistic is a function of the data which has the property of sufficiency with
respect to a statistical model and its associated unknown parameter, meaning that “no
other statistic which can be calculated from the same sample provides any additional
information as to the value of the parameter.” For example, if we assume that a variable is
distributed normally with a unit variance and an unknown expectation, then the average

function is a sufficient statistic.

22.5 A High Level View of Clustering 319

Consistency (Co) If d and d’ are dissimilarity functions over ¥, such that
for every a,y € 4, if x,y belong to the same cluster in F(4,d) then
d'(x,y) < d(x,y) and if x,y belong to different clusters in F(¥,d) then
d'(x,y) > d(x, y), then F(4#,d) = F(4,d’).

A moment of reflection reveals that the Scale Invariance is a very natura
requirement — it would be odd to have the result of a clustering function depen
on the units used to measure between-point distances. The Richness requirement
basically states that the outcome of the clustering function is fully controlled by
the function d, which is also a very intuitive feature. The third requirement,
Consistency, is the only requirement that refers to the basic (informal) definition
of clustering — we wish that similar points will be clustered together and tha
dissimilar points will be separated to different clusters, and therefore, if points
that already share a cluster become more similar, and points that are already

separated become even less similar to each other, the clustering function shoul
have even stronger “support” of its previous clustering decisions.
However, Kleinberg (2003) has shown the following “impossibility” result:

THEOREM 22.4 There exists no function, F, that satisfies all the three proper-
ties: Scale Invariance, Richness, and Consistency.

Proof Assume, by way of contradiction, that some F does satisfy all three

properties. Pick some domain set 4 with at least three points. By Richness,
there must be some d such that F(¥,d) = {{a}: x € X} and there also exists
some dz such that F(¥,d2) # F(4,d1).

Let a € Ry be such that for every x,y € Y, ado(x,y) > di(x,y). Let d3 =
ad 2. Consider F'(4,d3). By the Scale Invariance property of F', we should have
F(X,d3) = F(&X,dz). On the other hand, since all distinct x,y € 4X reside in
different clusters w.r.t. F(4,d1), and d3(z,y) > di(a,y), the Consistency of F
implies that F(4,d3) = F(4,d1). This is a contradiction, since we chose dj, d2
so that F(¥,d2) 4 F(X, d,).

It is important to note that there is no single “bad property” among the three
properties. For every pair of the the three axioms, there exist natural clustering
functions that satisfy the two properties in that pair (one can even construct such
examples just by varying the stopping criteria for the Single Linkage clustering
function). On the other hand, Kleinberg shows that any clustering algorithm
hat minimizes any center-based objective function inevitably fails the consis-
ency property (yet, the k-sum-of-in-cluster-distances minimization clustering
does satisfy Consistency).
The Kleinberg impossibility result can be easily circumvented by varying the

properties. For example, if one wishes to discuss clustering functions that have

a fixed number-of-clusters parameter, then it is natural to replace Richness by
k-Richness (namely, the requirement that every partition of the domain into k
subsets is attainable by the clustering function). k-Richness, Scale Invariance
and Consistency all hold for the k-means clustering and are therefore consistent.

320

22.6

22.7

22.8

Clustering

Alternatively, one can relax the Consistency property. For example, say that two
clusterings C = (Cy,...C,) and C’ = (C{,...C7) are compatible if for every
clusters C; € C and Ci € C’, either C; C Ci or Ci CCG; or G69 Ci = 0 (it is
worthwhile noting that for every dendrogram, every two clusterings that are ob-
tained by trimming that dendrogram are compatible). “Refinement Consistency”
is the requirement that, under the assumptions of the Consistency property, the
new clustering F(¥,d’) is compatible with the old clustering F(4,d). Many
common clustering functions satisfy this requirement as well as Scale Invariance
and Richness. Furthermore, one can come up with many other, different, prop-
erties of clustering functions that sound intuitive and desirable and are satisfied
by some common clustering functions.

There are many ways to interpret these results. We suggest to view it as indi-
cating that there is no “ideal” clustering function. Every clustering function will
inevitably have some “undesirable” properties. The choice of a clustering func-

tion for any given task must therefore take into account the specific properties

of that task. There is no generic clustering solution, just as there is no clas-
sification algorithm that will learn every learnable task (as the No-Free-Lunch
theorem shows). Clustering, just like classification prediction, must take into
account some prior knowledge about the specific task at hand.

Summary

Clustering is an unsupervised learning problem, in which we wish to partition
a set of points into “meaningful” subsets. We presented several clustering ap-
proaches including linkage-based algorithms, the k-means family, spectral clus-
tering, and the information bottleneck. We discussed the difficulty of formalizing
the intuitive meaning of clustering.

Bibliographic Remarks

The k-means algorithm is sometimes named Lloyd’s algorithm, after Stuart
Lloyd, who proposed the method in 1957. For a more complete overview of
spectral clustering we refer the reader to the excellent tutorial by Von Luxburg
(2007). The information bottleneck method was introduced by Tishby, Pereira
& Bialek (1999). For an additional discussion on the axiomatic approach see
Ackerman & Ben-David (2008).

Exercises

1. Suboptimality of k-Means: For every parameter t > 1, show that there
exists an instance of the k-means problem for which the k-means algorithm

22.8 Exercises 321

(might) find a solution whose k-means objective is at least t- OPT, where
OPT is the minimum k-means objective.

. k-Means Might Not Necessarily Converge to a Local Minimum:
Show that the k-means algorithm might converge to a point which is not
a local minimum. Hint: Suppose that k = 2 and the sample points are
{1,2,3,4} C R suppose we initialize the k-means with the centers {2, 4};
and suppose we break ties in the definition of C; by assigning i to be the
smallest value in argmin, ||x — 44;||-

3. Given a metric space (4, d), where || < 00, and k € N, we would like to find

a partition of XY into C),...,C; which minimizes the expression

Gaiam ((¥,d), (C1,...,Ck)) = mane diam(Cj),

where diam(C;) = maxy,./ec; d(a, x’) (we use the convention diam(C;) = 0
if |Cj| < 2).
Similarly to the k-means objective, it is NP-hard to minimize the k-
diam objective. Fortunately, we have a very simple approximation algorithm:
Initially, we pick some x € ¥ and set ju; = x. Then, the algorithm iteratively

sets

Vj € {2,...,k}, 4 =argmax min d(x, 1).
weX t€[j-1]

Finally, we set

Vi € [k], C; = {a € X : i = argmind(x, 4;)}.
J€|k]

Prove that the algorithm described is a 2-approximation algorithm. That
is, if we denote its output by Ci,...,C,, and denote the optimal solution by
Ct,...,Cf, then,

G—diam((¥,d), (C1, -..,Ck)) < 2+ Gxdiam((¥, d), (CX, ..., Cf).

Hint: Consider the point j1z.41 (in other words, the next center we would have
chosen, if we wanted k + 1 clusters). Let r = minis] d(14j, He41)- Prove the
following inequalities
Gy—diam((¥, 4), (C1, .--,Cn)) < 2r
Gx—diam((X,d),(CT,..-, Ch)) > r.

. Recall that a clustering function, F’, is called Center-Based Clustering if, for
some monotonic function f : Ry — R,, on every given input (V,d), F(4,d)
is a clustering that minimizes the objective

Gy((X,d), (Ci,...Ck)) = amin SO YS Fa pn),

where %’ is either ¥ or some superset of ¥.

322 Clustering

Prove that for every k > 1 the k-diam clustering function defined in the
previous exercise is not a center-based clustering function.
Hint: Given a clustering input (¥,d), with |4| > 2, consider the effect of
adding many close-by points to some (but not all) of the members of ¥, on
either the k-diam clustering or any given center-based clustering.
5. Recall that we discussed three clustering “properties”: Scale Invariance, Rich-
ness, and Consistency. Consider the Single Linkage clustering algorithm.
1. Find which of the three properties is satisfied by Single Linkage with the
Fixed Number of Clusters (any fixed nonzero number) stopping rule.
2. Find which of the three properties is satisfied by Single Linkage with the
Distance Upper Bound (any fixed nonzero upper bound) stopping rule.
3. Show that for any pair of these properties there exists a stopping criterion
for Single Linkage clustering, under which these two axioms are satisfied.
6. Given some number k, let k-Richness be the following requirement:

For any finite X and every partition C = (C1,...Cx) of & (into nonempty subsets)
there exists some dissimilarity function d over X such that F(X,d) =C.

Prove that, for every number k, there exists a clustering function that
satisfies the three properties: Scale Invariance, k-Richness, and Consistency.


23

Dimensionality Reduction

Dimensionality reduction is the process of taking data in a high dimensional

space and m:
This process

apping it into a new space whose dimensionality is much smaller.
is closely related to the concept of (lossy) compression in infor-

mation theory. There are several reasons to reduce the dimensionality of the

data. First, high dimensional data impose computational challenges. Moreover,

in some situations high dimensionality might lead to poor generalization abili-

ies of the le
sample comp

he mapping

finding meaningful structure of the data, and for illustration purposes.

arning algorithm (for example, in Nearest Neighbor classifiers the
lexity increases exponentially with the dimension—see Chapter 19).

Finally, dimensionality reduction can be used for interpretability of the data, for

In this chapter we describe popular methods for dimensionality reduction. In
hose methods, the reduction is performed by applying a linear transformation

o the original data. That is, if the original data is in R? and we want to embed
it into R” (n < d) then we would like to find a matrix W € R™¢ that induces

x > Wx. A natural criterion for choosing W is in a way that will

enable a reasonable recovery of the original x. It is not hard to show that in

general, exact recovery of x from Wx is impossible (see Exercise 1).

The first method we describe is called Principal Component Analysis (PCA).

In PCA, both the compression and the recovery are performed by linear transfor-

mations and
between the

Squared sense.

he method finds the linear transformations for which the differences
recovered vectors and the original vectors are minimal in the least

Next, we describe dimensionality reduction using random matrices W. We

derive an important lemma, often called the “Johnson-Lindenstrauss lemma,”

which analyz

technique.
Last, we s.

again a rand

es the distortion caused by such a random dimensionality reduction

how how one can reduce the dimension of all sparse vectors using
om matrix. This process is known as Compressed Sensing. In this

case, the recovery process is nonlinear but can still be implemented efficiently

using linear

rogramming.

We conclude by underscoring the underlying “prior assumptions” behind PCA

and compressed sensing, which can help us understand the merits and pitfalls of

the two methods.

Understanding

Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.
Personal use only. Not for distribution. Do not post.
Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

324

23.1

Dimensionality Reduction

Principal Component Analysis (PCA)

Let X1,...,Xm be m vectors in R¢. We would like to reduce the dimensional-
ity of these vectors using a linear transformation. A matrix W € R™4, where
n < d, induces a mapping x +> Wx, where Wx € R” is the lower dimensionality
representation of x. Then, a second matrix U € R&” can be used to (approxi-
mately) recover each original vector x from its compressed version. That is, for
a compressed vector y = Wx, where y is in the low dimensional space R”, we
can construct x = Uy, so that x is the recovered version of x and resides in the
original high dimensional space R?.

In PCA, we find the compression matrix W and the recovering matrix U so

that the total squared distance between the original and recovered vectors is
minimal; namely, we aim at solving the problem

m
argmin Ss \|x: — UWx;|[3. (23.1)
WeR™4,UER¢™ 4
To solve this problem we first show that the optimal solution takes a specific
form.

LEMMA 23.1 Let (U,W) be a solution to Equation (23.1). Then the columns of
U are orthonormal (namely, U'U is the identity matrix of R") and W =U".

Proof Fix any U,W and consider the mapping x +>» UWx. The range of this
mapping, R = {UWx: x € R4}, is an n dimensional linear subspace of R®. Let
V € R*” be a matrix whose columns form an orthonormal basis of this subspace,
namely, the range of V is R and V'V = I. Therefore, each vector in R can be
written as Vy where y € R”. For every x € R@ and y € R” we have

Lely Trt A T T
Ix—Vy| = [xP ty V "Vy —2y'V "x = |Ix|? + Ilyll? — 29" (V"),
where we used the fact that V'V is the identity matrix of R”. Minimizing the
preceding expression with respect to y by comparing the gradient with respect
to y to zero gives that y = V'x. Therefore, for each x we have that
VV 'x = argmin ||x — X||3.

XER
In particular this holds for xj,...,Xm and therefore we can replace U,W by
V,V' and by that do not increase the objective

m m

SO |i — UWxi|3 > SO xi — VV x I13.
i=l

i=1

Since this holds for every U, W the proof of the lemma follows.

On the basis of the preceding lemma, we can rewrite the optimization problem
given in Equation (23.1) as follows:
m
argmin Ss \|x; — UU Tx,|[3. (23.2)

UeR4n:UTUSI ay

23.1 Principal Component Analysis (PCA) 325

We further simplify the optimization problem by using the following elementary
algebraic manipulations. For every x € R¢@ and a matrix U € R*” such that
U'U =I we have

\|x — UU x|l? = |[x|]? — 2x’ UU x +x'UU' UU'x
= |x|? —x' UU x
= ||x||? — trace(U'xx'U), (23.3)

where the trace of a matrix is the sum of its diagonal entries. Since the trace is
a linear operator, this allows us to rewrite Equation (23.2) as follows:

m
argmax trace G Ss x10) : (23.4)

UERG":UTUSI i=l

Let A = a ja Xi x} . The matrix A is symmetric and therefore it can be
written using its spectral decomposition as A = vpv', where D is diagonal and
V'V = VV! =I. Here, the elements on the diagonal of D are the eigenvalues of
A and the columns of V are the corresponding eigenvectors. We assume without
loss of generality that D1,; > Dz. >--- > Daa. Since A is positive semidefinite
it also holds that Daa > 0. We claim that the solution to Equation (23.4) is
the matrix U whose columns are the n eigenvectors of A corresponding to the
largest n eigenvalues.

THEOREM 23.2 Let X1,...,Xm be arbitrary vectors in R?, let A= a 1 xix},

and let u1,...,Un ben eigenvectors of the matrix A corresponding to the largest
n eigenvalues of A. Then, the solution to the PCA optimization problem given
in Equation (23.1) is to set U to be the matrix whose columns are uy,...,Un
and to set W =U".

Proof Let VDV'' be the spectral decomposition of A. Fix some matrix U € R&”
with orthonormal columns and let B = V'U. Then, VB = vw'U=U.It
follows that

u' AU =B'V' VDV'VB=B'DB,

and therefore
d

trace(U' AU) = LPL Ble

Note that B'B = U'VV'U = U'U =I. Therefore, the columns of B are
also orthonormal, which implies that an vey Be, =n. In addition, let B €
R* be a matrix such that its first n columns are the columns of B and in
addition BB =I. Then, for every j we have al Be, = 1, which implies that
vi, B Be, <i. It follows that:

trace(U' AU) < D; ;8;
( ) Be[0,1l" lias 3 599)

326

23.1.1

23.1.2

Dimensionality Reduction

It is not hard to verify (see Exercise 2) that the right-hand side equals to
yi Dj,;. We have therefore shown that for every matrix U € R*” with or-
thonormal columns it holds that trace(U' AU) < Vier Dj;,;. On the other hand,
if we set U to be the matrix whose columns are the n leading eigenvectors of A
we obtain that trace(U' AU) = Va Di

and this concludes our proof.

J?

Remark 23.1 The proof of Theorem 23.2 also tells us that the value of the
objective of Equation (23.4) is 07, Di,;. Combining this with Equation (23.3)
and noting that 37”, ||x;||? = trace(A) = 7“, Dj; we obtain that the optima
objective value of Equation (23.1) is 1@ D

i=n41 Visi

Remark 23.2. It isa common practice to “center” the examples before applying
PCA. That is, we first calculate pp = a i, x: and then apply PCA on the
vectors (x1 — 4),...,(Xm— ). This is also related to the interpretation of PCA
as variance maximization (see Exercise 4).

A More Efficient Solution for the Case d >> m

In some situations the original dimensionality of the data is much larger than
the number of examples m. The computational complexity of calculating the
PCA solution as described previously is O(d?) (for calculating eigenvalues of A)
plus O(md?) (for constructing the matrix A). We now show a simple trick that
enables us to calculate the PCA solution more efficiently when d >> m.

Recall that the matrix A is defined to be ay xix). It is convenient to rewrite
A = X'X where X € R™¢ is a matrix whose ith row is x}. Consider the
matrix B = XX'. That is, B € R'" is the matrix whose i,j element equals

(x;,X;). Suppose that u is an eigenvector of B: That is, Bu = Au for some

 € R. Multiplying the equality by X' and using the definition of B we obtain
X'XXTu = AXTu. But, using the definition of A, we get that A(X'u) =
\(XTu). Thus, Tanti is an eigenvector of A with eigenvalue of A.

We can therefore calculate the PCA solution by calculating the eigenvalues of
B instead of A. The complexity is O(m?) (for calculating eigenvalues of B) and

m?d (for constructing the matrix B).

Remark 23.3 The previous discussion also implies that to calculate the PCA
solution we only need to know how to calculate inner products between vectors.
This enables us to calculate PCA implicitly even when d is very large (or even
infinite) using kernels, which yields the kernel PCA algorithm.

Implementation and Demonstration

A pseudocode of PCA is given in the following.

23.1 Principal Component Analysis (PCA) 327

1 He
Ly
7 at
oe
9 « @&,

05 . ep

Figure 23.1 A set of vectors in R? (blue x’s) and their reconstruction after
dimensionality reduction to R' using PCA (red circles).

PCA
input
A matrix of m examples X € R™4
number of components n
if (m > d)
A=X'X
Let uj,...,U, be the eigenvectors of A with largest eigenvalues
else
B=XxX"
Let vi,...,Vn be the eigenvectors of B with largest eigenvalues
fori=1,...,n set uj = pew svi
output: uj,...,Un
To illustrate how PCA works, let us generate vectors in R? that approximately
reside on a line, namely, on a one dimensional subspace of R?. For example,

suppose that each example is of the form (x,« + y) where x is chosen uniformly
at random from [—1, 1] and y is sampled from a Gaussian distribution with mean
0 and standard deviation of 0.1. Suppose we apply PCA on this data. Then, the
eigenvector corresponding to the largest eigenvalue will be close to the vector
(1/V2,1/V2). When projecting a point (2,2 + y) on this principal component
we will obtain the scalar 2“. The reconstruction of the original vector will be
((a + y/2), (w+ y/2)). In Figure 23.1 we depict the original versus reconstructed
data.

Next, we demonstrate the effectiveness of PCA on a data set of faces. We

extracted images of faces from the Yale data set (Georghiades, Belhumeur &

Kriegman 2001). Each image contains 50x50 = 2500 pixels; therefore the original
dimensionality is very high.

328

Dimensionality Reduction

eo A a ae oe

ae La | Eee ee! aX : ‘
e'Gne Qne GEE 9 +
BB |) | co ]

+ Hof | *

ew

Figure 23.2 Images of faces extracted from the Yale data set. Top-Left: the original
images in R°°*°°. Top-Right: the images after dimensionality reduction to R’® and
reconstruction. Middle row: an enlarged version of one of the images before and after
PCA. Bottom: The images after dimensionality reduction to R?. The different marks
indicate different individuals.

Some images of faces are depicted on the top-left side of Figure 23.2. Using
PCA, we reduced the dimensionality to R!° and reconstructed back to the orig-
inal dimension, which is 507. The resulting reconstructed images are depicted
on the top-right side of Figure 23.2. Finally, on the bottom of Figure 23.2 we
depict a 2 dimensional representation of the images. As can be seen, even from a
2 dimensional representation of the images we can still roughly separate different
individuals.

23.2

23.2 Random Projections 329

Random Projections

In this section we show that reducing the dimension by using a random linear
transformation leads to a simple compression scheme with a surprisingly low
distortion. The transformation x + Wx, when W is a random matrix, is often
referred to as a random projection. In particular, we provide a variant of a famous
lemma due to Johnson and Lindenstrauss, showing that random projections do
not distort Euclidean distances too much.

Let x1,X2 be two vectors in R?. A matrix W does not distort too much the
distance between x; and xg if the ratio

\|Wx1 — Wxe|
\|x1 — x2l|

is close to 1. In other words, the distances between x; and x2 before and after
the transformation are almost the same. To show that ||Wx1 — Wxa|| is not too
far away from ||x1 — Xg|| it suffices to show that W does not distort the norm of

the difference vector x = x; — X2. Therefore, from now on we focus on the ratio
||Wx||
xq . . ae . ae
We start with analyzing the distortion caused by applying a random projection

to a single vector.

LEMMA 23.3. Fix some x € R¢. Let W € R™4 be a random matrix such that
each W;,; is an independent normal random variable. Then, for every € € (0,3)
we have

1
Ilx|I?

> | a/vnywx||?

>e | < Qemen/6.

Proof Without loss of generality we can assume that ||x||? = 1. Therefore, an
equivalent inequality is

P[(L—e)n < ||Wx|? < (1+ 6)n] > 1-268".

Let w; be the ith row of W. The random variable (w;,x) is a weighted sum o:
d independent normal random variables and therefore it is normally distribute
with zero mean and variance )° , r = ||x||? = 1. Therefore, the random vari-
able ||Wx||? = S7y_,((wi,x))? has a x? distribution. The claim now follows
directly from a measure concentration property of .? random variables stated in

Lemma B.12 given in Section B.7.

The Johnson-Lindenstrauss lemma follows from this using a simple union
bound argument.

LEMMA 23.4 (Johnson-Lindenstrauss Lemma) Let Q be a finite set of vectors
in R¢. Let 6 € (0,1) and n be an integer such that

= [Seal — 5

330

23.3

Dimensionality Reduction

Then, with probability of at least 1—6 over a choice of a random matrix W € R™4
such that each element of W is distributed normally with zero mean and variance
of 1/n we have

2
sup |LE

<eé
xeQ| [IxI|? |

Proof Combining Lemma 23.3 and the union bound we have that for every

€ (0,3):

Wxll2
P [sup l | - i > ( < 2/Q| eo 7/6,
xeQ| [Ix|l

Let 5 denote the right-hand side of the inequality; thus we obtain that
= ,/ Slos2lal/s)
n

Interestingly, the bound given in Lemma 23.4 does not depend on the origina

dimension of x. In fact, the bound holds even if x is in an infinite dimensiona
Hilbert space.

Compressed Sensing

Compressed sensing is a dimensionality reduction technique which utilizes a prior
assumption that the original vector is sparse in some basis. To motivate com-
pressed sensing, consider a vector x € R¢ that has at most s nonzero elements.
That is,

f .
I1x\lo = [fe sa: A O}| <s.

Clearly, we can compress x by representing it using s (index,value) pairs. Fur-
thermore, this compression is lossless — we can reconstruct x exactly from the s
(index,value) pairs. Now, lets take one step forward and assume that x = Ua,
where a is a sparse vector, ||a||o < s, and U is a fixed orthonormal matrix. That
is, x has a sparse representation in another basis. It turns out that many nat-
ural vectors are (at least approximately) sparse in some representation. In fact,
this assumption underlies many modern compression schemes. For example, the

PEG-2000 format for image compression relies on the fact that natural images
are approximately sparse in a wavelet basis.
Can we still compress x into roughly s numbers? Well, one simple way to do
his is to multiply x by U', which yields the sparse vector a, and then represent
a by its s (index,value) pairs. However, this requires us first to “sense” x, to
store it, and then to multiply it by U'. This raises a very natural question: Why

go to so much effort to acquire all the data when most of what we get will be

hrown away? Cannot we just directly measure the part that will not end up

being thrown away?

23.3 Compressed Sensing 331

Compressed sensing is a technique that simultaneously acquires and com-
presses the data. The key result is that a random linear transformation can
compress x without losing information. The number of measurements needed is
order of slog(d). That is, we roughly acquire only the important information
about the signal. As we will see later, the price we pay is a slower reconstruction
phase. In some situations, it makes sense to save time in compression even at
he price of a slower reconstruction. For example, a security camera should sense
and compress a large amount of images while most of the time we do not need to
decode the compressed data at all. Furthermore, in many practical applications,
compression by a linear transformation is advantageous because it can be per-

formed efficiently in hardware. For example, a team led by Baraniuk and Kelly

has proposed a camera architecture that employs a digital micromirror array to
perform optical calculations of a linear transformation of an image. In this case,
obtaining each compressed measurement is as easy as obtaining a single raw

measurement. Another important application of compressed sensing is medical
imaging, in which requiring fewer measurements translates to less radiation for
he patient.

Informally, the main premise of compressed sensing is the following three “sur-
prising” results:

. It is possible to reconstruct any sparse signal fully if it was compressed by
x +» Wx, where W is a matrix which satisfies a condition called the Re-
stricted Isoperimetric Property (RIP). A matrix that satisfies this property is
guaranteed to have a low distortion of the norm of any sparse representable
vector.

2. The reconstruction can be calculated in polynomial time by solving a linear

program.

3. A random n x d matrix is likely to satisfy the RIP condition provided that n

is greater than an order of slog(d).

Formally,

DEFINITION 23.5 (RIP) A matrix W € R"¢ is (e,s)-RIP if for allx 40 s.t.
\[xllo < s we have
|x|5
IIx||3

-1/<e

The first theorem establishes that RIP matrices yield a lossless compression
scheme for sparse vectors. It also provides a (nonefficient) reconstruction scheme.

THEOREM 23.6 Let € <1 and let W be a (e,2s)-RIP matrix. Let x be a vector
s.t. ||x||o < 8, let y = Wx be the compression of x, and let

& € argmin ||v||o
v:Wv=y

be a reconstructed vector. Then, X = x.

332

Dimensionality Reduction

Proof We assume, by way of contradiction, that x # x. Since x satisfies the
constraints in the optimization problem that defines x we clearly have that
|Xllo < |Ixllo < s. Therefore, |x — X|]o < 2s and we can apply the RIP in-
equality on the vector x — X. But, since W(x — X) = 0 we get that |0—1| < «,

which leads to a contradiction.

The reconstruction scheme given in Theorem 23.6 seems to be nonefficient

because we need to minimize a combinatorial objective (the sparsity of v). Quite
surprisingly, it turns out that we can replace the combinatorial objective, ||v|lo,
with a convex objective, ||v||1, which leads to a linear programming problem that
can be solved efficiently. This is stated formally in the following theorem.

THEOREM 23.7 Assume that the conditions of Theorem 23.6 holds and that

1
€<aa Then,

x = argmin||v|/) = argmin ||/v||1.
v:Wv=y v:Wv=y
In fact, we will prove a stronger result, which holds even if x is not a sparse
vector.

THEOREM 23.8 Let € < Ts and let W be a (€,2s)-RIP matrix. Let x be an

arbitrary vector and denote

Xs © argmin ||x — v||1.
v:||vlloSs
That is, xs is the vector which equals x on the s largest elements of x and equals
0 elsewhere. Let y = Wx be the compression of x and let

x* € argmin ||v||1
v:Wv=y

be the reconstructed vector. Then,

l+pe ip

\|x* — x2 S?7T 8 \|x — Xs|l1,

where p = V2e/(1—€).

Note that in the special case that x = x, we get an exact recovery, x* = x, so
Theorem 23.7 is a special case of Theorem 23.8. The proof of Theorem 23.8 is
given in Section 23.3.1.

Finally, the third result tells us that random matrices with n > 0(slog(d)) are
likely to be RIP. In fact, the theorem shows that multiplying a random matrix
by an orthonormal matrix also provides an RIP matrix. This is important for
compressing signals of the form x = Ua@ where x is not sparse but @ is sparse.

if W is a random matrix and we compress using y = Wx then this
is the same as compressing @ by y = (WU)a and since WU is also RIP we can
reconstruct @ (and thus also x) from y.

23.3.1

23.3 Compressed Sensing 333

THEOREM 23.9 Let U be an arbitrary fixed d x d orthonormal matrix, let €,6
be scalars in (0,1), let s be an integer in [d], and let n be an integer that satisfies
slog(40d/(d €))

—_,—.

€

n = 100

Let W € R"4 be a matrix s.t. each element of W is distributed normally with
zero mean and variance of 1/n. Then, with proabability of at least 1—6 over the
choice of W, the matrix WU is (e,s)-RIP.

Proofs*

Proof of Theorem 23.8
We follow a proof due to Candés (2008).

Let h = x* — x. Given a vector v and a set of indices I we denote by v; the
vector whose ith element is v; if i € I and 0 otherwise.
The first trick we use is to partition the set of indices {d| = {1,...,d} into
disjoint sets of size s. That is, we will write [d] = Tp UT; UT)... Tajs—1 where
for all i, |T;| = s, and we assume for simplicity that d/s is an integer. We define
the partition as follows. In To we put the s indices corresponding to the s largest
elements in absolute values of x (ties are broken arbitrarily). Let Tf = [d] \ To.

Next, T; will be the s indices corresponding to the s largest elements in absolute
value of hye. Let To,1 = To UT; and TS, = [d] \To,1- Next, T2 will correspond to
the s largest elements in absolute value of hye ,. And, we will construct T3,7T4,...
in the same way.

To prove the theorem we first need the following lemma, which shows that
RIP also implies approximate orthogonality.

LEMMA 23.10 Let W be an (e,2s)-RIP matrix. Then, for any two disjoint sets
I,J, both of size at most s, and for any vector u we have that (Wu;,Wuyz) <
elluz|le use.

Proof W.1.0.g. assume ||ur||2 = ||uy||2 = 1.
|Wuy + Wuyl|3 — War — Was
7 .

But, since |.J UJ| < 2s we get from the RIP condition that ||Wu; + Wuj||3 <
(+e)(llur||3 + rasa) = 20. +e) and that —||Wuy—Wauy||3 < —(1—e)(\jur|3 +
|Juz|]3) = —2(1 — €), which concludes our proof.

(Wu, Wuz)

We are now ready to prove the theorem. Clearly,

[h\l2 = hx, + beg, l2 < [lz Ilo + [zs

OL 0,1

lo. (23.5)

To prove the theorem we will show the following two claims:

Claim 1:. ||hre, |l2 < ||, ||2 + 2s7!/?||x — xs|l1.-

Claim 2:. ||h7,, 2 < @%s71/?|k — x.|l1-

O1

1-p

334

Dimensionality Reduction

Combining these two claims with Equation (23.5) we get that
[hallo < [a7 Io + [Hors

OL

lz < 2I[lnr,,, 12 + 2571/7 [Ix — xsl
<2 (25 +1) Phx — xslh

=2

LTP ly sll,
—P

and this will conclude our proof.

Proving Claim 1:
To prove this claim we do not use the RIP condition at all but only use the fact
that x* minimizes the ¢; norm. Take j > 1. For each i € T; and ve Tj-1 we
have that |hi| < |hi|. Therefore, |\hz, ||oo < ||az,_, || /s. Thus,

lh, 2 < 8'/?|[bz; loo < 87/7 |b, |la-

Summing this over j = 2,3,... and using the triangle inequality we obtain that
rg, lo < 5° Ilhaz, lo < 87 1/? are lla (23.6)
j22

Next, we show that ||hz¢||; cannot be large. Indeed, from the definition of x*
we have that ||x||1 > ||x*||1 = ||x + hl|1. Thus, using the triangle inequality we

obtain that

IIx] > [lethally = SO farethal+ SO lithe] > [pero fl — [lar ll + hare lla — [lore lla
i€To ieT¢
(23.7)
and since ||xre||1 = |x — Xs|l1 = |[x\|1 — ||xzpl]1 we get that
Phar ll1 < [lar lla + 2lpxr5 Il. (23.8)

Combining this with Equation (23.6) we get that

W[zy Ile < 87 '/? (far [la + 2lbxz¢ Il) < [Haz lo + 2877? Ipxre lla,

OL

which concludes the proof of claim 1.

Proving Claim 2:
For the second claim we use the RIP condition to get that

(1 =) [ary (13 < Whe, , |. (23.9)

Since Why, , = Wh — 50,5. Whr, = — ))j39 Whz, we have that

p22
|Wha, ,|3 = — 50 (Whr,,, Whr,) = — $0 (Why, + Whe, , Whz,).
j22 j22
From the RIP condition on inner products we obtain that for all i € {1,2} and
j > 2 we have
|(Whr,, Whr,)| < ellar,

|2l|laz; |l2-

23.3 Compressed Sensing 335

Since |lh7, ||2 + |[hr, |lz < V2||hzy., 2 we therefore get that

Wha, .||3 < V2«l|bx,,, Ilo 5° Ilhz, ll2-

j22
Combining this with Equation (23.6) and Equation (23.9) we obtain

(l-e

I[lury,. [13 < V2el[bx7,,, [los 1/7 [Lure [la

Rearranging the inequality gives

V2€

hx, lz S s/?\Ihre
l-e

Finally, using Equation (23.8) we get that
[hex [12 < ps~'/? ([[baz lla + 2lb<rell1) < plllazy lz + 20877? [bere ll.
but since ||hz, ||2 < ||hz, , ||2 this implies

2
“PP -1/2

[har ll2 S y=

\l<x5||1,

which concludes the proof of the second claim.

Proof of Theorem 23.9
To prove the theorem we follow an approach due to (Baraniuk, Davenport, De-
Vore & Wakin 2008). The idea is to combine the Johnson-Lindenstrauss (JL)
lemma with a simple covering argument.

We start with a covering property of the unit ball.

LEMMA 23.11 Let € (0,1). There ezists a finite set Q C R¢ of size |Q| < (3)"
such that

sup min |/x—v]| < e.
x:|[x|<1_ VE@

Proof Let k be an integer and let
Q! = {x E Rt: Vj € [d, i € {-k, -k+1,...,k} st. xj = Zh.

Clearly, |Q’| = (2k + 1)4. We shall set Q = Q'N Bo(1), where Bo(1) is the unit
ly ball of R%. Since the points in Q’ are distributed evenly on the unit ¢,, ball,
the size of Q is the size of Q’ times the ratio between the volumes of the unit (2
and ¢,, balls. The volume of the @,, ball is 27 and the volume of Ba(1) is

qt/2
Td +d/2)"

For simplicity, assume that d is even and therefore

T(1+d/2) = (d/2)! > (22)"",

336

Dimensionality Reduction

where in the last inequality we used Stirling’s approximation. Overall we obtained
that

IQ] < (2k + 1)4 (m/e)? (d/2)-4? 2-4, (23.10)
Now lets specify k. For each x € Bo(1) let v € Q be the vector whose ith element

is sign(a,) ||a;|k|/k. Then, for each element we have that |x; — v;| < 1/k and
thus

vd

Ix—vll < =.

k

To ensure that the right-hand side will be at most € we shall set k = [Vd/e].
Plugging this value into Equation (23.10) we conclude that

|O| < (BV4/ (26) (w/ey"/? (a/2)-#”? = (2)/Z)* < (8)".

Let x be a vector that can be written as x = U@ with U being some orthonor-
mal matrix and ||a||o < s. Combining the earlier covering property and the JL
lemma (Lemma 23.4) enables us to show that a random W will not distort any
such x.

LEMMA 23.12 Let U be an orthonormal d x d matrix and let I C [d| be a set
of indices of size |I| = s. Let S be the span of {U; :i € I}, where U; is the ith
column of U. Let 6 € (0,1), € € (0,1), andn €N such that

log (2/5) +s log(12/e)

n> 24 3

€
Then, with probability of at least 1—6 over a choice of a random matrix W € R™4
such that each element of W is independently distributed according to N(0,1/n),
we have

xeS

Proof It suffices to prove the lemma for all x € S with ||x|| = 1. We can write
x = Uya where a € R*, |/a|/2 = 1, and U; is the matrix whose columns are
{U; : i € I}. Using Lemma 23.11 we know that there exists a set Q of size
|Q| < (12/e)* such that

s in |la — < 4).
sup min v|| < («/4)

@:||a|=1
But since U is orthogonal we also have that

s i =— < :
sup min ||Ure Urv|| < («/4)

:||o||=1

Applying Lemma 23.4 on the set {Urv : v € Q} we obtain that for n satisfying

23.3 Compressed Sensing 337

the condition given in the lemma, the following holds with probability of at least

1-06:

\|WUrv||?
sup -—1) <€/2,
veg] ||Urv|l? /
This also implies that
WU.
sup IWUrv ll _ ) < 6/2.
veq| ||Urv||
Let a be the smallest number such tha
W.
ves, WM cay,
II

Clearly a < oo. Our goal is to show that a < €. This follows from the fact that
for any x € S of unit norm there exists v € Q such that ||x — U;v|| < ¢/4 and
therefore

||Wx|]| < ||WUrv]| + ||W(x — Urv)|| < 14+ €/2 + (14 a)e/4.
Thus,
|x]

IIx!

Vx € S,

< 14+ (c/2+ (1+ a)e/4).

But the definition of a implies that

2+6/4
a<e/2+(l+a)e/4 as c — <e.
This proves that for all x € S we have el —1<e. The other side follows from

this as well since

||Wx|| > ||WUrv|| — ||W(« — Urv)|| > 1-€/2-(1+ 6)e/4 > 1.

The preceding lemma tells us that for x € S of unit norm we have
(16) < [Wx <1 +0),
which implies that
(1-26) < ||Wx||? < (1436).

The proof of Theorem 23.9 follows from this by a union bound over all choices

of I.

338

23.4

23.5

Dimensionality Reduction

PCA or Compressed Sensing?

Suppose we would like to apply a dimensionality reduction technique to a given
set of examples. Which method should we use, PCA or compressed sensing? In
his section we tackle this question, by underscoring the underlying assumptions
behind the two methods.

It is helpful first to understand when each of the methods can guarantee per-
‘ect recovery. PCA guarantees perfect recovery whenever the set of examples is
contained in an n dimensional subspace of R¢. Compressed sensing guarantees
perfect recovery whenever the set of examples is sparse (in some basis). On the
basis of these observations, we can describe cases in which PCA will be better
han compressed sensing and vice versa.

As a first example, suppose that the examples are the vectors of the standard

basis of R?, namely, e1,..., ea, where each e; is the all zeros vector except 1 in the
ith coordinate. In this case, the examples are 1-sparse. Hence, compressed sensing
will yield a perfect recovery whenever n > Q(log(d)). On the other hand, PCA
will lead to poor performance, since the data is far from being in an n dimensional

subspace, as long as n < d. Indeed, it is easy ro verify that in such a case, the
averaged recovery error of PCA (ie., the objective of Equation (23.1) divided by
m) will be (d — n)/d, which is larger than 1/2 whenever n < d/2.

We next show a case where PCA is better than compressed sensing. Consider

m examples that are exactly on an n dimensional subspace. Clearly, in such a
case, PCA will lead to perfect recovery. As to compressed sensing, note that
the examples are n-sparse in any orthonormal basis whose first n vectors span
the subspace. Therefore, compressed sensing would also work if we will reduce
the dimension to Q(nlog(d)). However, with exactly n dimensions, compressed
sensing might fail. PCA has also better resilience to certain types of noise. See
(Chang, Weiss & Freeman 2009) for a discussion.

Summary

We introduced two methods for dimensionality reduction using linear transfor-
mations: PCA and random projections. We have shown that PCA is optimal in
the sense of averaged squared reconstruction error, if we restrict the reconstruc-
tion procedure to be linear as well. However, if we allow nonlinear reconstruction,
PCA is not necessarily the optimal procedure. In particular, for sparse data, ran-
dom projections can significantly outperform PCA. This fact is at the heart of
the compressed sensing method.

23.6

23.7

23.6 Bibliographic Remarks 339

Bibliographic Remarks

PCA is equivalent to best subspace approximation using singular value decom-
position (SVD). The SVD method is described in Appendix C. SVD dates back
to Eugenio Beltrami (1873) and Camille Jordan (1874). It has been rediscovered
many times. In the statistical literature, it was introduced by Pearson (1901). Be-
sides PCA and SVD, there are additional names that refer to the same idea and
are being used in different scientific communities. A few examples are the Eckart-
Young theorem (after Carl Eckart and Gale Young who analyzed the method in
1936), the Schmidt-Mirsky theorem, factor anal}

Compressed sensing was introduced in Donoho (2006) and in (Candes & Tao
2005). See also Candes (2006).

, and the Hotelling transform.

Exercises

1. In this exercise we show that in the general case, exact recovery of a linear
compression scheme is impossible.
1. let A € R"? be an arbitrary compression matrix where n < d—1. Show
that there exists u,v € R", u # v such that Au = Av.
2. Conclude that exact recovery of a linear compression scheme is impossible.
2. Let a € R¢ such that a; > ag >--: > ag > 0. Show that
d

n
Be(0,1)": Pa cu Oe 98) » ’

Hint: Take every vector B € [0,1]? such that |||, <n. Let i be the minimal
index for which 3; < 1. If i = n+1 we are done. Otherwise, show that we can
increase §;, while possibly decreasing 8; for some j > i, and obtain a better
solution. This will imply that the optimal solution is to set 8; = 1 fori <n
and 8; =0 fori>n.

3. Kernel PCA: In this exercise we show how PCA can be used for construct-
ing nonlinear dimensionality reduction on the basis of the kernel trick (see
Chapter 16).
Let ¥ be some instance space and let S$ = {x1,..., .Xm} be a set of points

in ¥. Consider a feature mapping w : ¥ — V, where V is some Hilbert space

(possibly of infinite dimension). Let K : ¥ x ¥ be a kernel function, that is,
k(x,x’) = (w(x), Y(x’)). Kernel PCA is the process of mapping the elements
in S into V using 7, and then applying PCA over {y(x1),-...,%(Xm)} into

R". The output of this process is the set of reduced elements.

Show how this process can be done in polynomial time in terms of m
and n, assuming that each evaluation of K(-,-) can be calculated in a con-
stant time. In particular, if your implementation requires multiplication of

two matrices A and B, verify that their product can be computed. Similarly,

340 Dimensionality Reduction

if an eigenvalue decomposition of some matrix C is required, verify that this

decomposition can be computed.

4. An Interpretation of PCA as Variance Maximization:

Let X1,...,Xm, be m vectors in R@, and let x be a random vector distributed
according to the uniform distribution over x1,...,Xm. Assume that E[x] = 0.
1. Consider the problem of finding a unit vector, w € R*%, such that the

random variable (w,x) has maximal variance. That is, we would like to

solve the problem
i< 2
argmax Var[(w,x)] = argmax — So (iw, x:)) :
w:|[w||=1 w:||w||=1 7 Fay

Show that the solution of the problem is to set w to be the first principle

vector of X1,...,Xm-

2. Let wy be the first principal component as in the previous question. Now,
suppose we would like to find a second unit vector, w2 € R¢, that maxi-
mizes the variance of (w2,x), but is also uncorrelated to (w1,x). That is,
we would like to solve:

argmax Var[(w, x)].
w:||w||=1, E[((wi,x))((w,x))]=0
Show that the solution to this problem is to set w to be the second principal

component of X1,...,Xm-
Hint: Note that

E[((wi, x))((w, x))] = wl E[xx']w = mw] Aw,

where A = )>,x;x/. Since w is an eigenvector of A we have that the
constraint E[((w1,x))((w,x))] = 0 is equivalent to the constraint

(w1,w) = 0.

5. The Relation between SVD and PCA: Use the SVD theorem (Corol-
ary C.6) for providing an alternative proof of Theorem 23.2.

6. Random Projections Preserve Inner Products: The Johnson-Lindenstrauss
emma tells us that a random projection preserves distances between a finite

set of vectors. In this exercise you need to prove that if the set of vectors are
within the unit ball, then not only are the distances between any two vectors
preserved, but the inner product is also preserved.

Let Q be a finite set of vectors in R? and assume that for every x € Q we
have ||x|| <1.

. Let 6 € (0,1) and n be an integer such that

_— ,[SioslQP75) — 5

Prove that with probability of at least 1 — 6 over a choice of a random


23.7 Exercises 341

matrix W € R™4¢, where each element of W is independently distributed
according to N(0,1/n), we have

|(Wu, Wv) — (u,v)| <e

for every u,v € Q.
Hint: Use JL to bound both WW@*™)ll and he.

atv] u-vi|
. (*) Let x1,...,Xm be a set of vectors in R¢@ of norm at most 1, and assume
that these vectors are linearly separable with margin of y. Assume that
d > 1/77. Show that there exists a constant ¢ > 0 such that if we randomly
project these vectors into R”, for n = ¢/7?, then with probability of at least
99% it holds that the projected vectors are linearly separable with margin

9/2.

24

Generative Models

We started this book with a distribution free learning framework; namely, we

did not impose any assumptions on the underlying distribution over the data.

Furthermore, we followed a discriminative approach in which our goal is not to

learn the underlying distribution but rather to learn an accurate predictor. In

this chapter we describe a generative approach, in which it is assumed that the

underlying distribution over the data has a specific parametric form and our goal

is to estimate the parameters of the model. This task is called parametric density

estimation.

The discriminative approach has the advantage of directly optimizing the
quantity of interest (the prediction accuracy) instead of learning the underly-

ing distribution. This was phrased as follows by Vladimir Vapnik in his principle

for solving problems using a restricted amount of information:

When solving a given problem, try to avoid a more general problem as an intermediate

step.

Of course, if we succeed in learning the underlying distribution accurately,

we are considered to be “experts” in the sense that we can predict by using

the Bayes optimal classifier. The problem is that it is usually more difficult to

learn the underlying distribution than to learn an accurate predictor. However,

in some situations, it is reasonable to ado:
For example, sometimes it is easier (comput.
of the model than to learn a discriminative
we do not have a specific task at hand but
either for making predictions at a later time
or for the sake of interpretability of the da

We start with a popular statistical method

pt t
atio
re
rat.

a.

he generative learning approach.
nally) to estimate the parameters
ictor. Additionally, in some cases
her would like to model the data

without having to retrain a predictor

or estimating the parameters of

the data, which is called the maximum likelihood principle. Next, we describe two

generative assumptions which greatly simp!

ify

he learning process. We also de-

scribe the EM algorithm for calculating the maximum likelihood in the presence

of latent variables. We conclude with a brief description of Bayesian reasoning.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.
Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

24.1

24.1 Maximum Likelihood Estimator 343

Maximum Likelihood Estimator

Let us start with a simple example. A drug company developed a new drug to
treat some deadly disease. We would like to estimate the probability of survival
when using the drug. To do so, the drug company sampled a training set of m
people and gave them the drug. Let S = (x1,...,%m) denote the training set,
where for each i, x; = 1 if the ith person survived and x; = 0 otherwise. We can
model the underlying distribution using a single parameter, @ € [0, 1], indicating
the probability of survival.

We now would like to estimate the parameter @ on the basis of the training

set S. A natural idea is to use the average number of 1’s in S as an estimator.
That is,

~ Le
= mot (24.1)

Clearly, Es [6] = 6. That is, # is an unbiased estimator of 0. Furthermore, since is
the average of m i.i.d. binary random variables we can use Hoeffding’s inequality
to get that with probability of at least 1 — 6 over the choice of S' we have that

\}0-0| < eae). (24.2)

Another interpretation of 6 is as the Maximum Likelihood Estimator, as we
formally explain now. We first write the probability of generating the sample S:

P[S = (21,...,2%m)] Ilona pine: = ghee (1 — )EsG-2s),

i=1

We define the log likelihood of S', given the parameter @, as the log of the preceding
expression:

1(5;6) = log (P[S = (1,---2tm)]) = log(8) > Jari + log( — 8) D7 ~ a).

The maximum likelihood estimator is the parameter that maximizes the likeli-
hood

6 € argmax L(S;0). (24.3)
0

Next, we show that in our case, Equation (24.1) is a maximum likelihood esti-
mator. To see this, we take the derivative of L(S;@) with respect to 0 and equate
it to zero:

biti _ vid 3 -0
0 1-6 ,

Solving the equation for @ we obtain the estimator given in Equation (24.1).

344

24.1.1

Generative Models

Maximum Likelihood Estimation for Continuous Random Variables

Let X be a continuous random variable. Then, for most « € R we have PLX =
x] = 0 and therefore the definition of likelihood as given before is trivialized. To
overcome this technical problem we define the likelihood as log of the density of
the probability of X at x. That is, given an iid. training set S = (a1,...,U%m)
sampled according to a density distribution Pg we define the likelihood of S given
0 as

L(S;0) = log (i a) = » log(Pg (ai).

As before, the maximum likelihood estimator is a maximizer of L(S;@) with
respect to 0.

As an example, consider a Gaussian random variable, for which the density
function of X is parameterized by 0 = (4,0) and is defined as follows:

ruel= teen (HH),

We can rewrite the likelihood as

(a; — py)? — mlog(o V2 7).

i=1

L(S;0) = -—>
(530) = —y%5
To find a parameter 6 = (1,0) that optimizes this we take the derivative of the
likelihood w.r.t. 2 and w.r.t. 0 and compare it to 0. We obtain the following two
equations:

m

d 1
qe) = ee —H=0

d

. _i< _)y2
Ta (5:0) = a Dale wy F = 0

Solving the preceding equations we obtain the maximum likelihood estimates:

Note that the maximum likelihood estimate is not always an unbiased estimator.
For example, while ji is unbiased, it is possible to show that the estimate & of
the variance is biased (Exercise 1).

Simplifying Notation

To simplify our notation, we use P[X = 2] in this chapter to describe both the
probability that X = x (for discrete random variables) and the density of the
distribution at x (for continuous variables).

24.1.2

24.1.3

24.1 Maximum Likelihood Estimator 345

Maximum Likelihood and Empirical Risk Minimization

The maximum likelihood estimator shares some similarity with the Empirical
Risk Minimization (ERM) principle, which we studied extensively in previous
chapters. Recall that in the ERM principle we have a hypothesis class H and
we use the training set for choosing a hypothesis h € H that minimizes the
empirical risk. We now show that the maximum likelihood estimator is an ERM
for a particular loss function.

Given a parameter @ and an observation x, we define the loss of 6 on x as

(0, x) = —log(Po[a]). (24.4)

That is, ¢(0, x) is the negation of the log-likelihood of the observation x, assuming
the data is distributed according to Pg. This loss function is often referred to as
the log-loss. On the basis of this definition it is immediate that the maximum
likelihood principle is equivalent to minimizing the empirical risk with respect
to the loss function given in Equation (24.4). That is,

m

argmin ) 1(— log(Po{xi])) = argmax ) | log (Po |[a:])-

i=1 i=1

Assuming that the data is distributed according to a distribution P (not neces-
sarily of the parametric form we employ), the true risk of a parameter 6 becomes

E[L(,x)] = — 7} Pie] log(Pole))

Ere log (75) + 3 Pl) log (Fu): (24.5)

Dap[P||Po] H(P)

where Drr is called the relative entropy, and H is called the entropy func-
tion. The relative entropy is a divergence measure between two probabilities.
For discrete variables, it is always nonnegative and is equal to 0 only if the two

distributions are the same. It follows that the true risk is minimal when Pg = P.

The expression given in Equation (24.5) underscores how our generative as-
sumption affects our density estimation, even in the limit of infinite data. It
shows that if the underlying distribution is indeed of a parametric form, then by
choosing the correct parameter we can make the risk be the entropy of the distri-
bution. However, if the distribution is not of the assumed parametric form, even
the best parameter leads to an inferior model and the suboptimality is measured
by the relative entropy divergence.

Generalization Analysis

How good is the maximum likelihood estimator when we learn from a finite
training set?

346

Generative Models

To answer this question we need to define how we assess the quality of an approxi-
mated solution of the density estimation problem. Unlike discriminative learning,
where there is a clear notion of “loss,” in generative learning there are various
ways to define the loss of a model. On the basis of the previous subsection, one
natural candidate is the expected log-loss as given in Equation (24.5).

In some situations, it is easy to prove that the maximum likelihood principle
guarantees low true risk as well. For example, consider the problem of estimating
the mean of a Gaussian variable of unit variance. We saw previously that the

maximum likelihood estimator is the average: ju = Po

Pus
E  [é(ji,2) — (y*,x E lo a
onal (a2) (2",2)] w~N(u* 1) 6 ( Pa

1 wo bons
~5le— a? + Se A)

, 4%. Let p* be the optimal
parameter. Then,

+(uw—fi) Efe]

a~N(u*,1)
2 *)2
fe (ue) a)
ZT FE ie
1
(A — pr"). (24.6)

Next, we note that i is the average of m Gaussian variables and therefore it is
also distributed normally with mean j* and variance o*/m. From this fact we
can derive bounds of the form: with probability of at least 1 — 6 we have that
|fu — p*| < € where € depends on o*/m and on 6.

In some situations, the maximum likelihood estimator clearly overfits. For
example, consider a Bernoulli random variable X and let PLX = 1] = 6*. As
we saw previously, using Hoeffding’s inequality we can easily derive a guarantee
on |@* — 6| that holds with high probability (see Equation (24.2)). However, if
our goal is to obtain a small value of the expected log-loss function as defined in
Equation (24.5) we might fail. For example, assume that 6* is nonzero but very
small. Then, the probability that no element of a sample of size m will be 1 is
(1 — 6*)™, which is greater than e~?8"™. It follows that whenever m < 105(2)
the probability that the sample is all zeros is at least 50%, and in that case, the
maximum likelihood rule will set § = 0. But the true risk of the estimate 6 = 0
is

E [¢(0,x)| = 6*6(0, 1) + (1 — 0*)£(6, 0)

a~nd*
= & log(1/0) + (1 — 6*) log(1/(1 — 4))
= 0* log(1/0) = co.

This simple example shows that we should be careful in applying the maximum
likelihood principle.
To overcome overfitting, we can use the variety of tools we encountered pre-

24.2

24.3

24.2 Naive Bayes 347

viously in the book. A simple regularization technique is outlined in Exercise
2.

Naive Bayes

The Naive Bayes classifier is a classical demonstration of how generative as-
sumptions and parameter estimations simplify the learning process. Consider
the problem of predicting a label y € {0,1} on the basis of a vector of features
X = (x1,..., 2a), where we assume that each x; is in {0,1}. Recall that the Bayes
optimal classifier is
hpayes(x) = argmax P[Y = y|X = x].
ye{0,1}
To describe the probability function P[Y = y|X = x] we need 2% parameters,
each of which corresponds to P[Y = 1|X = x] for a certain value of x € {0,1}¢.
This implies that the number of examples we need grows exponentially with the
number of features.
In the Naive Bayes approach we make the (rather naive) generative assumption
that given the label, the features are independent of each other. That is,
d
PIX =x¥ =y)=[[ PL =al¥ =y).

i=l

With thi:
further simplified:

sumption and using Bayes’ rule, the Bayes optimal classifier can be

hpayes(X) = argmax P[Y = y|X =x]

ye {0,1}
= argmaxP[Y = y|PLX =x|Y =y]
ye {0,1}
d
= argmaxP[Y = y Il P(X; = xi|Y = y]. (24.7)
ye {0,1} na

That is, now the number of parameters we need to estimate is only 2d + 1.
Here, the generative assumption we made reduced significantly the number of
parameters we need to learn.

When we also estimate the parameters using the maximum likelihood princi-
ple, the resulting classifier is called the Naive Bayes classifier.

Linear Discriminant Analysis

Linear discriminant analysis (LDA) is another demonstration of how generative

assumptions simplify the learning process. As in the Naive Bayes classifier we

consider again the problem of predicting a label y € {0,1} on the basis of a

348

24.4

Generative Models

vector of features x = (x1,...,%q). But now the generative assumption is as
follows. First, we assume that P[Y = 1] = P[Y = 0] = 1/2. Second, we assume
that the conditional probability of X given Y is a Gaussian distribution. Finally,
the covariance matrix of the Gaussian distribution is the same for both values
of the label. Formally, let jp, 4, € R@ and let © be a covariance matrix. Then,
the density distribution is given by

1 1 Ty-1
P[X =xlY = y] On)pp exp (-3« — py) E(x H)) .
As we have shown in the previous section, using Bayes’ rule we can write

hpayes(X) = argmax P[Y = yJP[X = x|Y = y}.
ye{0,1}
This means that we will predict Mpayes(x) = 1 iff

PIY =1JP[X =xly = 1]
lo (Fy =0PIX=x|Y = i) > 0.

This ratio is often called the log-likelihood ratio.
In our case, the log-likelihood ratio becomes

(x = fo) =} (x = pg) — (x = py )7=T1 (x = py)

We can rewrite this as (w, x) + b where

w= (My, — Mo) So) and b= 5 (wg E "yo — EE wy). (24.8)

As a result of the preceding derivation we obtain that under the aforemen-
tioned generative assumptions, the Bayes optimal classifier is a linear classifier.
Additionally, one may train the classifier by estimating the parameter jo, [44
and ¥ from the data, using, for example, the maximum likelihood estimator.
With those estimators at hand, the values of w and b can be calculated as in
Equation (24.8).

Latent Variables and the EM Algorithm

In generative models we assume that the data is generated by sampling from
a specific parametric distribution over our instance space 1. Sometimes, it is
convenient to express this distribution using latent random variables. A natural
example is a mixture of k Gaussian distributions. That is, 4 = R¢ and we
assume that each x is generated as follows. First, we choose a random number in
{1,...,k}. Let Y be a random variable corresponding to this choice, and denote
PY = y] = cy. Second, we choose x on the basis of the value of Y according to
a Gaussian distribution

P[X =x|Y =y] oars 7 exp (-5 = py) S51 (x = 1,)) . (24.9)


24.4 Latent Variables and the EM Algorithm 349

Therefore, the density of X can be written as:

k
P[X =x) = SOPIY =y|P[X =x|Y =y]

k
1 1 ret
= div Baa, EP (-F- 1m) yy («= 1,)).
y=

Note that Y is a hidden variable that we do not observe in our data. Neverthe-
less, we introduce Y since it helps us describe a simple parametric form of the
probability of X.

More generally, let 6 be the parameters of the joint distribution of X and Y
(e.g., in the preceding example, 8 consists of c,, M,, and Ly, for ally =1,...,k).
Then, the log-likelihood of an observation x can be written as

k
log (Pe[X = x]) = log (>: Po[X =x, Y= i) .
y=1
Given an iid. sample, S = (xi,...,Xm), we would like to find @ that maxi-

mizes the log-likelihood of S,

m

L(0) = log | Po[X = xi]

i=1

m

= So log Pol[X = xi]

i=l

m k
= Ss ( Pol =x.¥ =u).
i=1 y=1

The maximun-likelihood estimator is therefore the solution of the maximization
problem

m k
argmax L(9) = argmax Slog ( Po[X =xi,Y = i) :
6 6 i=l y=

In many situations, the summation inside the log makes the preceding opti-
mization problem computationally hard. The Expectation-Mazimization (EM)
algorithm, due to Dempster, Laird, and Rubin, is an iterative procedure for
searching a (local) maximum of L(@). While EM is not guaranteed to find the
global maximum, it often works reasonably well in practice.

EM is designed for those cases in which, had we known the values of the latent
variables Y , then the maximum likelihood optimization problem would have been
tractable. More precisely, define the following function over m x k matrices and
the set of parameters 0:

mek

F(Q,0) = 3 Y- Qiy log (PolX =xi,¥ =y]).

i=1 y=1

350

24.4.1

Generative Models

If each row of Q defines a probability over the ith latent variable given X = x;,
then we can interpret F'(Q,@) as the expected log-likelihood of a training set
(x1, Y1),--+;(Xm;Ym), Where the expectation is with respect to the choice of
each y; on the basis of the 7th row of Q. In the definition of F’, the summation is
outside the log, and we assume that this makes the optimization problem with
respect to @ tractable:

ASSUMPTION 24.1 For any matrix Q € [0,1]"*, such that each row of Q sums
to 1, the optimization problem

argmax F(Q, 0)
@
is tractable.

The intuitive idea of EM is that we have a “chicken and egg” problem. On one

hand, had we known Q, then by our assumption, the optimization problem of
finding the best 6 is tractable. On the other hand, had we known the parameters
6 we could have set Qj,, to be the probability of Y = y given that X = x.
The EM algorithm therefore alternates between finding @ given Q and finding Q
given 0. Formally, EM finds a sequence of solutions (QM), a), (Q?), a), ee
where at iteration t, we construct (QU+, ott)) by performing two steps.

e Expectation Step: Set
QS) = Paw [Y = y|X =xi]- (24.10)

iy
This step is called the Expectation step, because it yields a new probabil-
ity over the latent variables, which defines a new expected log-likelihood
function over 0.

e Maximization Step: Set a+) to be the maximizer of the expected log-
likelihood, where the expectation is according to Q¢+):

a) = argmax F(Q“+), 6). (24.11)

(7)
By our assumption, it is possible to solve this optimization problem effi-
ciently.

The initial values of 0 and Q® are usually chosen at random and the

procedure terminates after the improvement in the likelihood value stops being
significant.

EM as an Alternate Maximization Algorithm
To analyze the EM algorithm, we first view it as an alternate maximization
algorithm. Define the following objective function

miok

GQ, 8) = F(Q,8) — S79) Qiylog(Qiy)-

i=1 y=1

24.4 Latent Variables and the EM Algorithm 351

The second term is the sum of the entropies of the rows of Q. Let

k
Q= {2 € [0,1 Vi, S7 Qin = i}
y=1

be the set of matrices whose rows define probabilities over [k]. The following
lemma shows that EM performs alternate maximization iterations for maximiz-
ing G.

LEMMA 24.2. The EM procedure can be rewritten as:

Qh) = argmax G(Q,0)
QeQ

ett) = argmax G(QU'+))@) .
)

Furthermore, G(Q°*) 9) = L(a).
Proof Given Q+)) we clearly have that

aremax G(Q“t), 6) = argmax F(Q*)), 6).
) 2)

Therefore, we only need to show that for any @, the solution of argmaxgeg G(Q, 4)
is to set Qi = Po[Y = y|X = x;]. Indeed, by Jensen’s inequality, for any Q € Q
we have that

m k x _
410.0 =3- (Sra (MA =H)

i=1 \y=1
m k
Po[X =xi,Y =1
< Ss (1 ( 0,,Mkser aul)
i=l y=1 uy

m k
= Ss ( Pol =x.¥ =)
i=l y=1

= » log (Pe[X = xi]) = L(@),

352 Generative Models

while for Qi, = Pe[Y = y|X = xi] we have

G(Q,@) => (> PolY = ylX = xi]log (Fee = —))

i=1 \y=1

miok

= 0 PolY = y|X = xi] log (Po[X = xi])
i=1 y=1

m k

= So log (PolX = xi]) )> Pol¥ = y|X = xi]

= SC log (Po[X = xi]) = L(8).

This shows that setting Qi,y = Pe[Y = y|X = x;] maximizes G(Q, 0) over Q € Q
and shows that G(Q¢+)),@) = L(@®).

The preceding lemma immediately implies:

THEOREM 24.3. The EM procedure never decreases the log-likelihood; namely,
for allt,

LOY) > L(A).
Proof By the lemma we have

L(o'*)) _ G(Qe), +) > G(Qe) 9) _ L(6).

24.4.2 EM for Mixture of Gaussians (Soft k-Means)

Consider the case of a mixture of k Gaussians in which @ is a triplet (c, {41,-.., 44}, {21,---, Ue})
where Po[Y = y] = cy and Pe[X = x|Y = y] is as given in Equation (24.9). For
simplicity, we assume that ©; = Ny = --- = Ly = I, where I is the identity

matrix. Specifying the EM algorithm for this case we obtain the following:

e Expectation step: For each i € [m] and y € [k] we have that

1
Pow lY =y|X =x] = 5 Powl¥ = 9] Pow |X =xil¥ = y]
A
aro) 1 (2
= Fey? exp ( — Zl — wy? I). (24.12)
i

where Z; is a normalization factor which ensures that Yy Pow [Y = y|X =
x;| sums to 1.

e Maximization step: We need to set 0'*" to be a maximizer of Equation (24.11),

24.5

24.5 Bayesian Reasoning 353

which in our case amounts to maximizing the following expression w.r.t. ¢
and p:
mk

YD Powl¥ =viX =x) (loeley) Flos —syl?)- 23)

i=1y=1
Comparing the derivative of Equation (24.13) w.r.t. 4, to zero and rear-
ranging terms we obtain:
Lu, = Dies Pow Y= ylX = xi) x
YY Pow ¥ = ylX = xi] 7

That is, 4, is a weighted average of the x; where the weights are according

to the probabilities calculated in the E step. To find the optimal c we need
to be more careful since we must ensure that c is a probability vector. In
Exercise 3 we show that the solution is:

Dita Pow [Y = |X = xi
yer wits Pow [Y = y/|X = xi]

(24.14)

It is interesting to compare the preceding algorithm to the k-means algorithm
described in Chapter 22. In the k-means algorithm, we first assign each example
to a cluster according to the distance ||x; — y,||. Then, we update each center

1, according to the average of the examples assigned to this cluster. In the EM

approach, however, we determine the probability that each
each cluster. Then, we update the cent

ers on the basis of a

example belongs to
weighted sum over

the entire sample. For this reason, the EM approach for k-means is sometimes

called “soft k-means.”

Bayesian Reasoning

The maximum likelihood estimator follows a frequentist ap

that we refer to the parameter 6 as a fixed parameter and

that we do not know its value. A different approach to pa

roach. This means
he only problem is
rameter estimation

is called Bayesian reasoning. In the Bayesian approach, our uncertainty about

@ is also modeled using probability theory.

variable as well and refer to the distribution P(6] as a prior

name indicates, the prior distribution should be defined by

observing the data.

As an example, let us consider again the drug company

new drug. On the basis of past experience, the statisticians a

That is, we thin!

k of @ as a random
distribution. As its
he learner prior to

which developed a

the drug company

believe that whenever a drug has reached the level of clinic experiments on

people, it is likely to be effective. They mo
density distribution on 6 such that

0.8 if A>0.5
0.2 if 0<05

el this prior belief by defining a

(24.15)

354

Generative Models

As before, given a specific value of 6, it is assumed that the conditional proba-
bility, PLX = x|6], is known. In the drug company example, X takes values in
{0,1} and P[X = 2|6] = 6"(1—0)!-*.

Once the prior distribution over 6 and the conditional distribution over X
given @ are defined, we again have complete knowledge of the distribution over
X. This is because we can write the probability over X as a marginal probability

PIX =a] =) PIX = 2,6] = >> PLOPLX = a6],
0 6

where the last equality follows from the definition of conditional probability. If
@ is continuous we replace P[@] with the density function and the sum becomes
an integral:

X =a] = [Pe P(X = 26] do

Seemingly, once we know P[X = zl], a training set S = (x1,...,2m) tells us
nothing as we are already experts who know the distribution over a new point
X. However, the Bayesian view introduces dependency between S and X. This is
because we now refer to @ as a random variable. A new point X and the previous
points in S are independent only conditioned on 6. This is different from the
frequentist philosophy in which @ is a parameter that we might not know, but
since it is just a parameter of the distribution, a new point X and previous points
S are always independent.

In the Bayesian framework, since X and S are not independent anymore, what

we would like to calculate is the probability of X given S, which by the chain
rule can be written as follows:

X =2|S]= DPX = 2/0, 5] P[o|S] = LP ix = 26] P[0|S].

The second inequality follows from the assumption that X and S are independent
when we condition on 6. Using Bayes’ rule we have

_ [6]
Pls]

and together with the assumption that points are independent conditioned on 6,

we can write
m

Pe\s] a py HP 1/6) Pl.

We therefore obtain the following expression for Bayesian prediction:

m

PIX = aS] a 2/6] [7x = 2;|0| P(d). (24.16)
6

Getting back to our drug company example, we can rewrite P[|X = 2|S] as
1

PIX = al] = 5g

; fo (1 — 9) FEC) pig) do

24.6

24.7

24.6 Summary 355

It is interesting to note that when P[6] is uniform we obtain that

Pix =a

S] x fer ry — gy ethi ei) gg,

Solving the preceding integral (using integration by parts) we obtain

gj — t+

X=1
pP m+2

Recall that the prediction according to the maximum likelihood principle in this
case is P[X = 1|6] = =+“. The Bayesian prediction with uniform prior is rather
similar to the maximum likelihood prediction, except it adds “pseudoexamples”

to the training set, thus biasing the prediction toward the uniform prior.

Maximum A Posteriori

In many situations, it is difficult to find a closed form solution to the integral
given in Equation (24.16). Several numerical methods can be used to approxi-
mate this integral. Another popular solution is to find a single @ which maximizes
P[6|S]. The value of 6 which maximizes P[6|S] is called the Maximum A Poste-
riort estimator. Once this value is found, we can calculate the probability that

X = given the maximum a posteriori estimator and independently on S.

Summary

In the generative approach to machine learning we aim at modeling the distri-
bution over the data. In particular, in parametric density estimation we further
assume that the underlying distribution over the data has a specific paramet-
ric form and our goal is to estimate the parameters of the model. We have
described several principles for parameter estimation, including maximum like-
lihood, Bayesian estimation, and maximum a posteriori. We have also described
several specific algorithms for implementing the maximum likelihood under dif-
ferent assumptions on the underlying data distribution, in particular, Naive
Bayes, LDA, and EM.

Bibliographic Remarks

The maximum likelihood principle was studied by Ronald Fisher in the beginning
of the 20th century. Bayesian statistics follow Bayes’ rule, which is named after
the 18th century English mathematician Thomas Bayes.

There are many excellent books on the generative and Bayesian approaches
to machine learning. See, for example, (Bishop 2006, Koller & Friedman 2009,
MacKay 2003, Murphy 2012, Barber 2012).

356

24.8

Generative Models

Exercises

. Prove that the maximum likelihood estimator of the variance of a Gaussian
variable is biased.

. Regularization for Maximum Likelihood: Consider the following regularized
loss minimization:

© ¥-log(1/Palizi) + — (log(1/8) + tog(1/(1 ~ 8).

Show that the preceding objective is equivalent to the usual empirical error
had we added two pseudoexamples to the training set. Conclude that
the regularized maximum likelihood estimator would be

~ 1 m
6= ——|1 a).

Derive a high probability bound on (0 —0*|. Hint: Rewrite this as \0-E(6] +
E(6] — 6*| and then use the triangle inequality and Hoeffding inequality.

Use this to bound the true risk. Hint: Use the fact that now 6 > =H to
relate |9 — 9*| to the relative entropy.

Consider a general optimization problem of the form:

k
max ) 7 ¥y log(cy) s.t. cy > 0, So ey =l1,
y

y=

where v € R* is a vector of nonnegative weights. Verify that the M step
of soft k-means involves solving such an optimization problem.

Let c* = sy vy. Show that c* is a probability vector.
‘y

y
Show that the optimization problem is equivalent to the problem:

: * ; =
min Drx(e*||c) st. cy > 0, So ey =1.
y

Using properties of the relative entropy, conclude that c* is the solution to
the optimization problem.

25

Feature Selection and Generation

In the beginning of the book, we discussed
which the prior knowledge utilize
of the hypothesis class. However,
have so far ignored: How do we represent the
the papayas learning problem, we proposed t
the softness-color two dimensional!
to represent a papaya as a two dimensional
and color. Only after that did we choose the

class of mappings from the plane into the labe:

plane. Tha

the abstract model of learning, in

by the learner is fully encoded by the choice
here is another modeling choice, which we

instance space V? For example, in
he hypothesis class of rectangles in
is, our first modeling choice was
point corresponding to its softness

hypothesis class of rectangles as a

set. The transformation from the

real world object “papaya” into the scalar representing its softness or its color

is called a feature function or a

eature for short; namely, any measurement of

the real world object can be regarded as a feature. If Y is a subset of a vector

space, each x € ¥ is sometimes referred to as a feature vector. It is important to

understand that the way we enco
by itsel

Furthermore, even when we already have

prior knowledge about the problem.

resente

different

e real worl

objects as an instance space 1 is

an instance space 4 which is rep-

as a subset of a vector space, we might still want to change it into a
representation and apply a hypothesis class on top of it. That is, we

may define a hypothesis class on 4 by composing some class H on top of a

feature function which maps 4 into some other vector space 4’. We have al-

ready encountered examples of such compositions — in Chapter 15 we saw that

kernel-based SVM learns a composition of the class of halfspaces over a feature

mapping y that maps each original instance in ¥ into some Hilbert space. And,

indeed, the choice of yw is another form of prior knowledge we impose on the

problem.

In this chapter we study several methods

for constructing a good feature set.

We start with the problem of feature selection, in which we have a large pool

of features and our goal is to select a sma

1 number of features that will be

used by our predictor. Next, we discuss feature manipulations and normalization.

These include simple transformations that we

apply on our original features. Such

transformations may decrease the sample complexity of our learning algorithm,

its bias, or its computational complexity. Las

; we discuss several approaches for

feature learning. In these methods, we try to automate the process of feature

construction.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.
Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

358

25.1

Feature Selection and Generation

We emphasize that while there are some common techniques for feature learn-
ing one may want to try, the No-Free-Lunch theorem implies that there is no ulti-
mate feature learner. Any feature learning algorithm might fail on some problem.
In other words, the success of each feature learner relies (sometimes implicitly)
on some form of prior assumption on the data distribution. Furthermore, the
relative quality of features highly depends on the learning algorithm we are later
going to apply using these features. This is illustrated in the following example.

Example 25.1 Consider a regression problem in which ¥ = R?, Y = R, and
he loss function is the squared loss. Suppose that the underlying distribution
is such that an example (x,y) is generated as follows: First, we sample 1 from
he uniform distribution over [—1,1]. Then, we deterministically set y = 217.

Finally, the second feature is set to be x2 = y+ z, where z is sampled from the
uniform distribution over [—0.01, 0.01]. Suppose we would like to choose a single
eature. Intuitively, the first feature should be preferred over the second feature
as the target can be perfectly predicted based on the first feature alone, while it

cannot be perfectly predicted based on the second feature. Indeed, choosing the

first feature would be the right choice if we are later going to apply polynomial
regression of degree at least 2. However, if the learner is going to be a linear
regressor, then we should prefer the second feature over the first one, since the
optimal linear predictor based on the first feature will have a larger risk than

he optimal linear predictor based on the second feature.

Feature Selection

Throughout this section we assume that X = R%. That is, each instance is repre-
sented as a vector of d features. Our goal is to learn a predictor that only relies
on k < d features. Predictors that use only a small subset of features require a
smaller memory footprint and can be applied faster. Furthermore, in applications
such as medical diagnostics, obtaining each possible “feature” (e.g., test result)
can be costly; therefore, a predictor that uses only a small number of features
is desirable even at the cost of a small degradation in performance, relative to
a predictor that uses more features. Finally, constraining the hypothesis class to
use a small subset of features can reduce its estimation error and thus prevent
overfitting.

Ideally, we could have tried all subsets of k out of d features and choose the
subset which leads to the best performing predictor. However, such an exhaustive
search is usually computationally intractable. In the following we describe three

computationally feasible approaches for feature selection. While these methods
cannot guarantee finding the optimal subset, they often work reasonably well in

practice. Some of the methods come with formal guarantees on the quality of the
selected subsets under certain assumptions. We do not discuss these guarantees
here.

25.1.1

25.1 Feature Selection 359

Filters

Maybe the simplest approach for feature selection is the filter method, in which
we assess individual features, independently of other features, according to some
quality measure. We can then select the k features that achieve the highest score
(alternatively, decide also on the number of features to select according to the
value of their scores).
Many quality measures for features have been proposed in the literature.
Maybe the most straightforward approach is to set the score of a feature ac-
cording to the error rate of a predictor that is trained solely by that feature.
To illustrate this, consider a linear regression problem with the squared loss.
Let v = (21,j,...,%m,j) € R™ be a vector designating the values of the jth
feature on a training set of m examples and let y = (y1,---,Ym) € R™ be the

values of the target on the same m examples. The empirical squared loss of an
ERM linear predictor that uses only the jth feature would be

1
in —|lav+b—y|,
ain | llav yl’,
where the meaning of adding a scalar b to a vector v is adding b to all coordinates
of v. To solve this problem, let 6 = i ye, vi be the averaged value of the
feature and let y¥ = Pa 1 yi be the averaged value of the target. Clearly (see
Exercise 1),

1 1
i +b—yl|? = mi —d)+b- 7) ||. 25.1
main, — lav yl" = min — lla(v — 2) Yy- all (25.1)

Taking the derivative of the right-hand side objective with respect to b and
comparing it to zero we obtain that b = 0. Similarly, solving for a (once we know
that b = 0) yields a = (v—¥,y — y)/||v — o||?. Plugging this value back into the
objective we obtain the value

((v=8.y —9))?

—a 2 —
lly — all v-oP

Ranking the features according to the minimal loss they achieve is equivalent
to ranking them according to the absolute value of the following score (where
now a higher score yields a better feature):

(v-%y-9) a(v—v,y—9)
lv — >| ly — g/l Vala Valy - a?

The preceding expression is known as Pearson’s correlation coefficient. The nu-

(25.2)

merator is the empirical estimate of the covariance of the jth feature and the
target value, E[(v — Ev)(y — Ey)], while the denominator is the squared root of
the empirical estimate for the variance of the jth feature, E[(v — Ev)?], times
the variance of the target. Pearson’s coefficient ranges from —1 to 1, where if
the Pearson’s coefficient is either 1 or —1, there is a linear mapping from v to y
with zero empirical risk.

360

25.1.2

Feature Selection and Generation

If Pearson’s coefficient equals zero it means that the optimal linear function
from v to y is the all-zeros function, which means that v alone is useless for
predicting y. However, this does not mean that v is a bad feature, as it might
be the case that together with other features v can perfectly predict y. Indeed,
consider a simple example in which the target is generated by the function y =
2% + 2x2. Assume also that x, is generated from the uniform distribution over
{+1}, and rg = $01 + $2, where z is also generated i.i.d. from the uniform
distribution over {+1}. Then, E[z,] = E[a] = Ely] = 0, and we also have

Ely] = Efaq] + 2E[x2a1] = E[xy] — Ely] + E[zxi] = 0.

Therefore, for a large enough training set, the first feature is likely to have a
Pearson’s correlation coefficient that is close to zero, and hence it will most
probably not be selected. However, no function can predict the target value well
without knowing the first feature.

There are many other score functions that can be used by a filter method.
Notable examples are estimators of the mutual information or the area under
the receiver operating characteristic (ROC) curve. All of these score functions
suffer from similar problems to the one illustrated previously. We refer the reader
to Guyon & Elisseeff (2003).

Greedy Selection Approaches

Greedy selection is another popular approach for feature selection. Unlike filter
methods, greedy selection approaches are coupled with the underlying learning
algorithm. The simplest instance of greedy selection is forward greedy selection.
We start with an empty set of features, and then we gradually add one feature
at a time to the set of selected features. Given that our current set of selected
features is I, we go over all i ¢ I, and apply the learning algorithm on the set
of features I U {i}. Each such application yields a different predictor, and we
choose to add the feature that yields the predictor with the smallest risk (on

the training set or on a validation set). This process continues until we either

select k features, where k is a predefined budget of allowed features, or achieve
an accurate enough predictor.
Example 25.2 (Orthogonal Matching Pursuit) To illustrate the forward
greedy selection approach, we specify it to the problem of linear regression with
the squared loss. Let X € R™“ be a matrix whose rows are the m training
instances. Let y € R™ be the vector of the m labels. For every i € [d], let X;
be the ith column of X. Given a set I C [d] we denote by X; the matrix whose
columns are {X; : 7 € I}.

The forward greedy selection method starts with Io = (. At iteration t, we
look for the feature index j;, which is in

aremi j gy — y||2
argmin min |X7,_,ug;w — yIl?-

25.1 Feature Selection 361

Then, we update J; = I; U {jr}.

We now describe a more efficient implementation of the forward greedy selec-
tion approach for linear regression which is called Orthogonal Matching Pursuit
(OMP). The idea is to keep an orthogonal basis of the features aggregated so
far. Let V; be a matrix whose columns form an orthonormal basis of the columns
of Xy,.

Clearly,

min || X7,w — y||? = min ||Vi8 — y||?.

We will maintain a vector 0; which minimizes the right-hand side of the equation.

Initially, we set Ip = 0, Vo = 0, and 0; to be the empty vector. At round t, for
every j, we decompose X; = vj + uj where vj; = VV, X; is the projection
of X; onto the subspace spanned by V;_1 and u; is the part of X; orthogonal to
Vi-1 (see Appendix C). Then,

min ||V;10 + au; — y||?
6,0

= min [|[18 — y|? +07 |Juj|)? + 2a(u;,Vi18 — y))]
= min [|[-18 — y|? +0” uy? + 2a(uj, -y)]

= min [|[18 — y||?] + min [a*|ju;||* — 20(uj.y)]
= [[|Ve-14-1 — y|?] + min [a? |/uy||? — 20(uj,y)]

2
“ye, ye Mew)?
Vi-19x-1 — yl nig

It follows that we should select the feature

; ((uj,y))?
je = argmax 2
j \jw; ||?

The rest of the update is to se’

_ uj _ _ (Uj)
vi= [Vou mpl 0.=[A0: Ta; I |

The OMP procedure maintains an orthonormal basis of the selected features,
where in the preceding description, the orthonormalization property is obtained
by a procedure similar to Gram-Schmidt orthonormalization. In practice, the

Gram-Schmidt procedure is often numerically unstable. In the pseudocode that
follows we use SVD (see Section C.4) at the end of each round to obtain an
orthonormal basis in a numerically stable manner.

362

Feature Selection and Generation

Orthogonal Matching Pursuit (OMP)

input:
data matrix X € R™4, labels vector y € R™,
budget of features T
initialize: I, = 0
fort=1,...,T
use SVD to find an orthonormal basis V € R™‘~! of X7,
(for t = 1 set V to be the all zeros matrix)
foreach j € [d] \ I; let uj = Xj —VV' X,
2
let jp = argmaxj¢ 1,:\Ju;||>0 veoh
update [p41 = I, U {jr}
output [741

More Efficient Greedy Selection Criteria
Let R(w) be the empirical risk of a vector w. At each round of the forward

greedy selection method, and for every possible j, we should minimize R(w)
over the vectors w whose support is [;_; U {j}. This might be time consuming.
A simpler approach is to choose j; that minimizes

argmin min R(w;—1 + 7e;),
3 OER
where e; is the all zeros vector except 1 in the jth element. That is, we keep
the weights of the previously chosen coordinates intact and only optimize over
the new variable. Therefore, for each j we need to solve an optimization problem
over a single variable, which is a much easier task than optimizing over t.

An even simpler approach is to upper bound R(w) using a “simple” function
and then choose the feature which leads to the largest decrease in this upper
bound. For example, if R is a 6-smooth function (see Equation (12.5) in Chap-
ter 12), then

)

R(w

Ow;

R(w + ne;) < Rw) +72 + Br? /2.

Minimizing the right-hand side over 7 yields 7 = —

ae . 3 and plugging this

value into the above yields

2
Rw 4 e3) < Rw) — 5 5") ,

This value is minimized if the partial derivative of R(w) with respect to wy; is
maximal. We can therefore choose j; to be the index of the largest coordinate of
the gradient of R(w) at w.

Remark 25.3 (AdaBoost as a Forward Greedy Selection Procedure) It is pos-
sible to interpret the AdaBoost algorithm from Chapter 10 as a forward greedy

25.1.3

25.1 Feature Selection 363

selection procedure with respect to the function

m d

R(w) = log Ss exp [| —yi Ss wyh;(xi) . (25.3)

i=1 j=l

See Exercise 3.

Backward Elimination
Another popular greedy selection approach is backward elimination. Here, we
start with the full set of features, and then we gradually remove one feature at a
time from the set of features. Given that our current set of selected features is I,
we go over alli € I, and apply the learning algorithm on the set of features I\ {i}.
Each such application yields a different predictor, and we choose to remove the
feature i for which the predictor obtained from J \ {i} has the smallest risk (on
the training set or on a validation set).

Naturally, there are many possible variants of the backward elimination idea.

It is also possible to combine forward and backward greedy steps.

Sparsity-Inducing Norms

The problem of minimizing the empirical risk subject to a budget of k features
can be written as

minLZs(w) s.t. |l/wllo <k,
w

where!
IIwllo = His ws £ OF).

In other words, we want w to be sparse, which implies that we only need to
measure the features corresponding to nonzero elements of w.

Solving this optimization problem is computationally hard (Natarajan 1995,
Davis, Mallat & Avellaneda 1997). A possible relaxation is to replace the non-
convex function ||w||o with the ¢; norm, ||w||; = 74, |w;|, and to solve the
problem

minLs(w) st. |lwll1 < ki, (25.4)
w
where k; is a parameter. Since the ¢; norm is a convex function, this problem

can be solved efficiently as long as the loss function is convex. A related problem
is minimizing the sum of Ls(w) plus an ¢; norm regularization term,

min (Lg(w) + Al|w||), (25.5)
w
where A is a regularization parameter. Since for any k; there exists a \ such that
1 The function |] - ||o is often referred to as the 9 norm. Despite the use of the “norm”

notation, || - |]o is not really a norm; for example, it does not satisfy the positive
homogeneity property of norms, ||aw||o 4 |a| ||wllo-

364

Feature Selection and Generation

Equation (25.4) and Equation (25.5) lead to the same solution, the two problems
are in some sense equivalent.
The @; regularization often induces sparse solutions. To illustrate this, let us

i

art with the simple optimization problem

1
min (Se aw + ul) : (25.6)

weR

el

is easy to verify (see Exercise 2) that the solution to this problem is the “soft

ct

hresholding” operator
w = sign(2x) [Ja] — A], , (25.7)

where [a], a max{a,0}. That is, as long as the absolute value of x is smaller

than A, the optimal solution will be zero.
Next, consider a one dimensional regression problem with respect to the squared
loss:

1 :
argmin { —— S (xjw — y;)* + Alw| ] .
weR™ (4 > . .
We can rewrite the problem as
1 m
argmin (; (: >) w— (: Ss xiyi) w+Aalwl).
werm 7 i=1

For simplicity let us assume that + 7,2? = 1, and denote (x,y) = 07", vii:

then the optimal solution is

w =sign((x,y)) [|oe.y)|/m— Al...

That is, the solution will be zero unless the correlation between the feature x
and the labels vector y is larger than A.

Remark 25.4 Unlike the 4; norm, the ¢2 norm does not induce sparse solutions.
Indeed, consider the problem above with an 2 regularization, namely,

1< :
argmin (4 SC (aiw —y)r+ ow?) :

weRm i=1
Then, the optimal solution is

(x,y)/m
[IP /m + 2a"

w=

This solution will be nonzero even if the correlation between x and y is very small.
In contrast, as we have shown before, when using ¢) regularization, w will be
nonzero only if the correlation between x and y is larger than the regularization
parameter X.

25.2

25.2 Feature Manipulation and Normalization 365

Adding ¢; regularization to a linear regression problem with the squared loss
yields the LASSO algorithm, defined as

1
argmin { ——||Xw—y||? +A . 25.
engin (XW yl? +All) (25.8)

Under some assumptions on the distribution and the regularization parameter
A, the LASSO will find sparse solutions (see, for example, (Zhao & Yu 2006)
and the references therein). Another advantage of the ¢; norm is that a vector
with low ¢; norm can be “sparsified” (see, for example, (Shalev-Shwartz, Zhang
& Srebro 2010) and the references therein).

Feature Manipulation and Normalization

Feature manipulations or normalization include simple transformations that we
apply on each of our original features. Such transformations may decrease the
approximation or estimation errors of our hypothesis class or can yield a faster
algorithm. Similarly to the problem of feature selection, here again there are no
absolute “good” and “bad” transformations, but rather each transformation that
we apply should be related to the learning algorithm we are going to apply on
the resulting feature vector as well as to our prior assumptions on the problem.

To motivate normalization, consider a linear regression problem with the
squared loss. Let X € R™ 4 be a matrix whose rows are the instance vectors
and let y € R™ be a vector of target values. Recall that ridge regression returns
the vector

1
argmin | —||Xw — y|| + Allw||?] = (2Am2 + XTX) 1XTy.
w= =Lm

Suppose that d = 2 and the underlying data distribution is as follows. First we

sample y uniformly at random from {+1}. Then, we set x; to be y+0.5a, where

a is sampled uniformly at random from {+1}, and we set x2 to be 0.0001y. Note
that the optimal weight vector is w* = [0; 10000], and Lp(w*) = 0. However,
the objective of ridge regression at w* is \10°. In contrast, the objective of ridge
regression at w = [1;0] is likely to be close to 0.25 + X. It follows that whenever
r»> pes = 0.25 x 1078, the objective of ridge regression is smaller at the
suboptimal solution w = [1;0]. Since A typically should be at least 1/m (see
the analysis in Chapter 13), it follows that in the aforementioned example, if the
number of examples is smaller than 10° then we are likely to output a suboptimal
solution.

The crux of the preceding example is that the two features have completely
different scales. Feature normalization can overcome this problem. There are
many ways to perform feature normalization, and one of the simplest approaches
is simply to make sure that each feature receives values between —1 and 1. In

the preceding example, if we divide each feature by the maximal value it attains

366

Feature Selection and Generation

we will obtain that 7; = ut05a and ay = y. Then, for \ < 1073 the solution of
ridge regression is quite close to w*.

Moreover, the generalization bounds we have derived in Chapter 13 for reg-
ularized loss minimization depend on the norm of the optimal vector w* and
on the maximal norm of the instance vectors.” Therefore, in the aforementioned
example, before we normalize the features we have that ||w*||? = 10°, while af-
ter we normalize the features we have that ||w*||? = 1. The maximal norm of
the instance vector remains roughly the same; hence the normalization greatly
improves the estimation error.

Feature normalization can also improve the runtime of the learning algorithm.
For example, in Section 14.5.3 we have shown how to use the Stochastic Gradient
Descent (SGD) optimization algorithm for solving the regularized loss minimiza-
tion problem. The number of iterations required by SGD to converge also depends
on the norm of w* and on the maximal norm of ||x||. Therefore, as before, using
normalization can greatly decrease the runtime of SGD.

Next, we demonstrate in the following how a simple transformation on features,
such as clipping, can sometime decrease the approximation error of our hypoth-

esis class. Consider again linear regression with the squared loss. Let a > 1 be

a large number, suppose that the target y is chosen uniformly at random from
{+1}, and then the single feature x is set to be y with probability (1 — 1/a)
and set to be ay with probability 1/a. That is, most of the time our feature is

bounded but with a very small probability it gets a very high value. Then, for
any w, the expected squared loss of w is

1
Lp(w) =E (we —y)
1\1 11 =
= (1 - *) sly — 9)? + = 5(awy — 9)”.

Solving for w we obtain that w* = wh. which goes to zero as a goes to infin-
ity. Therefore, the objective at w* goes to 0.5 as a goes to infinity. For example,
for a = 100 we will obtain Lp(w*) > 0.48. Next, suppose we apply a “clipping”
transformation; that is, we use the transformation x +> sign(x) min{1, |x|}. Then,
following this transformation, w* becomes 1 and Lp(w*) = 0. This simple ex-
ample shows that a simple transformation can have a significant influence on the
approximation error.

Of course, it is not hard to think of examples in which the same feature trans-
formation actually hurts performance and increases the approximation error.
This is not surprising, as we have already argued that feature transformations
2 More precisely, the bounds we derived in Chapter 13 for regularized loss minimization

depend on ||w*||? and on either the Lipschitzness or the smoothness of the loss function.

For linear predictors and loss functions of the form ¢(w, (x, y)) = 6((w,x),y), where ¢ is

convex and either 1-Lipschitz or 1-smooth with respect to its first argument, we have that

¢ is either ||x||-Lipschitz or ||x||?-smooth. For example, for the squared loss,

o(a,y) = $(a — y)?, and &(w, (x, y)) = 3 ((w, x) — y)? is ||x||?-smooth with respect to its

first argument.

25.2.1

25.2 Feature Manipulation and Normalization 367

should rely on our prior assumptions on the problem. In the aforementioned ex-
ample, a prior assumption that may lead us to use the “clipping” transformation
is that features that get values larger than a predefined threshold value give us no
additional useful information, and therefore we can clip them to the predefined
threshold.

Examples of Feature Transformations

We now list several common techniques for feature transformations. Usually, it
is helpful to combine some of these transformations (e.g., centering + scaling).
In the following, we denote by f = (f1,.--, fm) € R™ the value of the feature f
over the m training examples. Also, we denote by f = a ye fi the empirical
mean of the feature over all examples.

Centering:
This transformation makes the feature have zero mean, by setting f; ¢ fi — f.

Unit Range:

This transformation makes the range of each feature be [0,1]. Formally, let
fmax = max; f; and fmin = min; f;. Then, we set fi < ee Similarly,
we can make the range of each feature be [—1,1] by the transformation f; <—
2 fbn —1. Of course, it is easy to make the range [0,6] or [—b, b], where b is
a user-specified parameter.

Standardization:

This transformation makes all features have a zero mean and unit variance.
Formally, let v = Po 7 (fi — f)? be the empirical variance of the feature.
Then, we set f; <— af

Clipping:

This transformation clips high or low values of the feature. For example, f; <
sign(f;) max{b, | fi|}, where 6 is a user-specified parameter.

Sigmoidal Transformation:

As its name indicates, this transformation applies a sigmoid function on the
feature. For example, f; < TreeR? where b is a user-specified parameter.
This transformation can be thought of as a “soft” version of clipping: It has a
small effect on values close to zero and behaves similarly to clipping on values
far away from zero.

368

25.3

25.3.1

Feature Selection and Generation

Logarithmic Transformation:

The transformation is f; < log(b+ f;), where b is a user-specified parameter. This
is widely used when the feature is a “counting” feature. For example, suppose
that the feature represents the number of appearances of a certain word in a
text document. Then, the difference between zero occurrences of the word and
a single occurrence is much more important than the difference between 1000
occurrences and 1001 occurrences.

Remark 25.5 In the aforementioned transformations, each feature is trans-
formed on the basis of the values it obtains on the training set, independently
of other features’ values. In some situations we would like to set the parameter
of the transformation on the basis of other features as well. A notable example
is a transformation in which one applies a scaling to the features so that the
empirical average of some norm of the instances becomes 1.

Feature Learning

So far we have discussed feature selection and manipulations. In these cases, we
start with a predefined vector space R®, representing our features. Then, we select
a subset of features (feature selection) or transform individual features (feature
transformation). In this section we describe feature learning, in which we start
with some instance space, ¥, and would like to learn a function, pW : ¥ > R¢,
which maps instances in ¥ into a representation as d-dimensional feature vectors.
The idea of feature learning is to automate the process of finding a good rep-
resentation of the input space. As mentioned before, the No-Free-Lunch theorem
ells us that we must incorporate some prior knowledge on the data distribution
in order to build a good feature representation. In this section we present a few
eature learning approaches and demonstrate conditions on the underlying data

distribution in which these methods can be useful.

Throughout the book we have already seen several useful feature construc-
ions. For example, in the context of polynomial regression, we have mapped the
original instances into the vector space of all their monomials (see Section 9.2.2
in Chapter 9). After performing this mapping, we trained a linear predictor on
op of the constructed features. Automation of this process would be to learn
a transformation w : ¥ — R®, such that the composition of the class of linear

predictors on top of w yields a good hypothesis class for the task at hand.
In the following we describe a technique of feature construction called dictio-
nary learning.

Dictionary Learning Using Auto-Encoders

The motivation of dictionary learning stems from a commonly used represen-
tation of documents as a “bag-of-words”: Given a dictionary of words D =
{w1,...,wx}, where each w; is a string representing a word in the dictionary,

25.3 Feature Learning 369

and given a document, (p1,...,pa), where each p; is a word in the document,
we represent the document as a vector x € {0, 1}, where 2; is 1 if w; = p; for
some j € [d], and x; = 0 otherwise. It was empirically observed in many text
processing tasks that linear predictors are quite powerful when applied on this
representation. Intuitively, we can think of each word as a feature that measures
some aspect of the document. Given labeled examples (e.g., topics of the doc-
uments), a learning algorithm searches for a linear predictor that weights these
features so that a right combination of appearances of words is indicative of the
label.

While in text processing there is a natural meaning to words and to the dic-

tionary, in other applications we do not have such an intuitive representation

of an instance. For example, consider the computer vision application of object
recognition. Here, the instance is an image and the goal is to recognize which
object appears in the image. Applying a linear predictor on the pixel-based rep-
resentation of the image does not yield a good classifier. What we would like
to have is a mapping 7 that would take the pixel-based representation of the
image and would output a bag of “visual words,” representing the content of the
image. For example, a “visual word” can be “there is an eye in the image.” If
we had such representation, we could have applied a linear predictor on top of

this representation to train a classifier for, say, face recognition. Our question is,

therefore, how can we learn a dictionary of “visual words” such that a bag-of-

words representation of an image would be helpful for predicting which object
appears in the image?

A first naive approach for dictionary learning relies on a clustering algorithm
(see Chapter 22). Suppose that we learn a function c: Y — {1,...,k}, where
c(x) is the cluster to which x belongs. Then, we can think of the clusters as
“words,” and of instances as “documents,” where a document x is mapped to
) € {0,1}*, where u(x); is 1 if and only if x belongs to the ith
cluster. Now, it is straightforward to see that applying a linear predictor on w(x)

the vector y)

tal

is equivalent to assigning the same target value to all instances that belong to
the same cluster. Furthermore, if the clustering is based on distances from a
class center (e.g., k-means), then a linear predictor on 7(x) yields a piece-wise
constant predictor on x.

Both the k-means and PCA approaches can be regarded as special cases of a
more general approach for dictionary learning which is called auto-encoders. In an
auto-encoder we learn a pair of functions: an “encoder” function, y) : R¢ > R*,
and a “decoder” function, ¢ : R* + R¢. The goal of the learning process is to
find a pair of functions such that the reconstruction error, }>; ||x; — $(W(xi))||?,
is small. Of course, we can trivially set k = d and both w,¢@ to be the identity
mapping, which yields a perfect reconstruction. We therefore must restrict 7 and
¢ in some way. In PCA, we constrain & < d and further restrict 7 and ¢ to be
linear functions. In k-means, k is not restricted to be smaller than d, but now
w and ¢ rely on k centroids, pr,...,44,, and ~#(x) returns an indicator vector

370

25.4

Feature Selection and Generation

in {0,1}* that indicates the closest centroid to x, while ¢ takes as input an
indicator vector and returns the centroid representing this vector.

An important property of the k-means construction, which is key in allowing
k to be larger than d, is that ~ maps instances into sparse vectors. In fact, in

k-means only a single coordinate of (x) is nonzero. An immediate extension of
the k-means construction is therefore to restrict the range of w to be vectors with
at most s nonzero elements, where s is a small integer. In particular, let w and ¢
be functions that depend on py,..., 14;,. The function ~ maps an instance vector
x to a vector u(x) € R*, where u(x) should have at most s nonzero elements.
The function ¢(v) is defined to be an v;u;. As before, our goal is to have a
small reconstruction error, and therefore we can define

= argmin ||x — ¢(v)||?_ s.t. ||vllo < s,
v

where ||v||o = |{j : vj # 0}|. Note that when s = 1 and we further restrict ||v||; =
1 then we obtain the k-means encoding function; that is, ~(x) is the indicator
vector of the centroid closest to x. For larger values of s, the optimization problem
in the preceding definition of 7) becomes computationally difficult. Therefore, in
practice, we sometime use ¢; regularization instead of the sparsity constraint and
define 7 to be

W(x) = argmin [|x — 6(v)|? + Allv|hi] ,

where A > 0 is a regularization parameter. Anyway, the dictionary learning
problem is now to find the vectors p4,..., W,, such that the reconstruction er-
ror, iy lle — H(#(%))I?
the ¢, regularization, this is still a computationally hard problem (similar to

is as small as possible. Even if w is defined using

the k-means problem). However, several heuristic search algorithms may give
reasonably good solutions. These algorithms are beyond the scope of this book.

Summary

Many machine learning algorithms take the feature representation of instances
for granted. Yet the choice of representation requires careful attention. We dis-
cussed approaches for feature selection, introducing filters, greedy selection al-
gorithms, and sparsity-inducing norms. Next we presented several examples for
feature transformations and demonstrated their usefulness. Last, we discussed
feature learning, and in particular dictionary learning. We have shown that fea-
ture selection, manipulation, and learning all depend on some prior knowledge
on the data.

25.5

25.6

25.5 Bibliographic Remarks 371

Bibliographic Remarks

Guyon &

Elisseeff (2003) surveyed several feature selection procedures, including

many types of filters.

Forwar

ject to a polyhedron constraint date back to the Frank-Wolfe algorithm (Frank

& Wolfe
including,
2008, Shal

signal pro

greedy selection procedures for minimizing a convex objective sub-

956). The relation to boosting has been studied by several authors,
(Warmuth, Liao & Ratsch 2006, Warmuth, Glocer & Vishwanathan
ev-Shwartz & Singer 2008). Matching pursuit has been studied in the
cessing community (Mallat & Zhang 1993). Several papers analyzed

greedy se

Shwartz, Zhang & Srebro (2010) and the references therein.

The use

shirani (1996) and the references therein), and much work has been done on un-
derstanding the relationship between the £;-norm and sparsity. It is also closely

related to

lection methods under various conditions. See, for example, Shalev-

of the ¢;-norm as a surrogate for sparsity has a long history (e.g. Tib-

compressed sensing (see Chapter 23). The ability to sparsify low ¢;

norm predictors dates back to Maurey (Pisier 1980-1981). In Section 26.4 we

also show
predictor.
Feature

that low ¢,; norm can be used to bound the estimation error of our

learning and dictionary learning have been extensively studied recently

in the context of deep neural networks. See, for example, (Lecun & Bengio 1995,

Hinton et

al. 2006, Ranzato et al. 2007, Collobert & Weston 2008, Lee et al.

2009, Le et al. 2012, Bengio 2009) and the references therein.

Exercises

1. Prove the equality given in Equation (25.1). Hint: Let a*,b* be minimizers of
the left-hand side. Find a,b such that the objective value of the right-hand

side is

direction.

smaller than that of the left-hand side. Do the same for the other

2. Show that Equation (25.7) is the solution of Equation (25.6).
3. AdaBoost as a Forward Greedy Selection Algorithm: Recall the Ad-

aBoost

algorithm from Chapter 10. In this section we give another interpre-

tation of AdaBoost as a forward greedy selection algorithm.

e Given a set of m instances x1,...,Xm, and a hypothesis class H of finite

VC dimension, show that there exist d and hi,..., ha such that for every

h

EH there exists i € [d] with h;(x;) = h(x,;) for every j € [m].

e Let R(w) be as defined in Equation (25.3). Given some w, define fy to be
the function

d

fw) = D0 wihi(.)-

i=l

372 Feature Selection and Generation

Let D be the distribution over [m| defined by
exp(—vifw(%i))
Z ,

where Z is a normalization factor that ensures that D is a probability
vector. Show that

Di=

OR(w)

Wj

m
=- Ss Diyysh; (xi).
i=l

Furthermore, denoting €; = ian DiMn;(x:)4yi]; Show that

OR(w) = 2; —1.
Ww;
Conclude that if e; < 1/2 — 7 then ont > 7/2.

e Show that the update of AdaBoost guarantees R(w(+)) — R(w) <
log(\/1 — 42). Hint: Use the proof of Theorem 10.2.

Part IV

Advanced Theory


26

26.1

Rademacher Complexities

In Chapter 4 we have shown that uniform convergence is a sufficient condition
for learnability. In this chapter we study the Rademacher complexity, which
measures the rate of uniform convergence. We will provide generalization bounds
based on this measure.

The Rademacher Complexity

Recall the definition of an e-representative sample from Chapter 4, repeated here
for convenience.

DEFINITION 26.1 (e-Representative Sample) A training set S is called e-representative
(w.r.t. domain Z, hypothesis class H, loss function ¢, and distribution D) if
sup |Lp(h) — Ls(h)| <e.
heH
We have shown that if S is an €/2 representative sample then the ERM rule
is consistent, namely, Lp(ERM7(S)) < minnex Lp(h) + €.
To simplify our notation, let us denote

def def

FS loH = {z4 lh,z): he H},

and given f € F, we define
Lol) = EU]. Ls()= => slei.-
‘i=1

We define the representativeness of S with respect to F as the largest gap be-
tween the true error of a function f and its empirical error, namely,

Repp(F.8) = sup (Lp(f) — Ls(f)). (26.1)
SEF

Now, suppose we would like to estimate the representativeness of S' using the
sample S only. One simple idea is to split S into two disjoint sets, S = $1 U S2;
refer to S; as a validation set and to Sp as a training set. We can then estimate
the representativeness of S' by

sup (Ls, (f) — Ls.(f))- (26.2)
SEF

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

376

Rademacher Complexities

This can be written more compactly by defining o = (01,...,¢m) € {£1}™ to
be a vector such that S$, = {z; : oj = 1} and Sy = {z; : 0; = —1}. Then, if we
further assume that |$)| = “ then Equation (26.2) can be rewritten as

— sup oif (zi). (26.3)
mre

The Rademacher complexity measure captures this idea by considering the ex-
pectation of the above with respect to a random choice of o. Formally, let Fo S
be the set of all possible evaluations a function f € F can achieve on a sample
S, namely,

FoS ={(flet)s---+f(em)) 2 f © Fh.

Let the variables in o be distributed i.i.d. according to P{o; = 1] = Plo; = —1] =
3. Then, the Rademacher complexity of F with respect to S' is defined as follows:

m

sup So oif(a)]- (26.4)

feF

i

m ony

R(F oS)

More generally, given a set of vectors, A C R™, we define

sup » ves . (26.5)

R(A) & =k

mM © |aca’

The following lemma bounds the expected value of the representativeness of
S' by twice the expected Rademacher complexity.
LEMMA 26.2

«Sl RepolF,5)| < 2B R(FeS).

Proof Let S’ = {z,...,z),} be another iid. sample. Clearly, for all f € F,
Lp(f) =Eg:[Lg:(f)]. Therefore, for every f € F we have

Lolf)—Ls(f) = ElLs(f)]- £s(f) = Elbs(f) — Es(f)].

Taking supremum over f € F of both sides, and using the fact that the supremum
of expectation is smaller than expectation of the supremum we obtain

sup (Lo(f)—Ls(f)) = sup ElLs:(f)— Ls(f))

feF fer 8
< E su (eon) ~tsin) |.
SEF

Taking expectation over S on both sides we obtain

E| sup (Lo(f) — Ls( ) < E | sup ae

[6F SS’) fer im
, 7 (26.6)

=— sup (F(Z .

mn | mp Eyer se]


26.1 The Rademacher Complexity 377

Next, we note that for each j, z; and 2, are i.i.d. variables. Therefore, we can
replace them without affecting the expectation:

E,| sup | (f(2)) - fla) + OU) - fled) ]] =

SiS’ a
a “a (26.7)
E,| sup | (f(z) — f(2))) + OU) — fl)

S,S!
feF xj

Let o; be a random variable such that P(o; = 1] = Plo; = —1) = 1/2. From
Equation (26.7) we obtain that

sup | o5(F (25) — f(z) + FE)

S,S/,0; | per Zz

1 1
g (Lbs. of Equation (26.7)) + (rhs. of Equation (26.7)) (26.8)

E sup (F(4) — Fle) + UE) Fo)

8, s
iAj
Repeating this for all 7 we obtain that

sup LU) — (zi) | ~ oF,

m

sw oi(f(zi) — f(z)) | - (26.9)

Finally,

sup Dail S( 2) f(z%)) )< sup Dail (a )+ sup) aisle)

SEF SEF

and since the probability of o is the same as the probability of —o, the right-hand
side of Equation (26.9) can be bounded by

o| edie oif (2) + +p Este |

SEF feF*

= meEIR( (Fo $')] + mE[R(F 0 8)] = 2mE[R(F 0 S)].

The lemma immediately yields that, in expectation, the ERM rule finds a

hypothesis which is close to the optimal hypothesis in H.
THEOREM 26.3 We have

E,,, Ep (ERMy(5)) — Ls(ERMy(5))] <2 EB R(lo Ho S).

Furthermore, for any h* © H

em [Lp(ERMyx(S)) — Lp(h*)| < 2 en RoHS).

378

Rademacher Complexities

Furthermore, if h* = argmin; Lp(h) then for each 5 € (0,1) with probability of
at least 1 — 6 over the choice of S we have

2 Es:wpm R(LoH oS")
a

Proof The first inequality follows directly from Lemma 26.2. The second in-

Lp(ERMyx(S)) — Lp(h*) <

equality follows because for any fixed h*,

Lp(h*) = E[Ls(h*)] > B[Ls(ERMy(S))].

Ss

The third inequality follows from the previous inequality by relying on Markov’s
inequality (note that the random variable Lp(ERMy(S)) — Lp(h*) is nonnega-

tive).

Next, we derive bounds similar to the bounds in Theorem 26.3 with a better
dependence on the confidence parameter 6. To do so, we first introduce the
following bounded differences concentration inequality.

LEMMA 26.4 (McDiarmid’s Inequality) Let V be some set and let f: V" >R
be a function of m variables such that for some c > 0, for alli € [m] and for all

Z1,.--,Lm, 2, EV we have
|f(@1, ++, am) — far, ++ @i-1, Bi, Pig1,-+-,Um)| Se
Let X1,...,Xm be m independent random variables taking values in V. Then,

with probability of at least 1— 6 we have

|f(X,-.-,Xm) — E[f(X1,...,Xm)]| < ey/m (2) m/2.

On the basis of the McDiarmid inequality we can derive generalization bounds
with a better dependence on the confidence parameter.

THEOREM 26.5 Assume that for all z and h € H we have that |¢(h, z)| < c.
Then,

1. With probability of at least 1 — 4, for allh € H,
2 In(2/6)

m

Lp(h)—Ls(h) < 2 B, RloWos!) + ey)

In particular, this holds for h =ERMy(S).
2. With probability of at least 1— 6, for allh EH,

Lp(h)—Lg(h) < 2R(LoHoS)+4c4/ enh)

In particular, this holds for h =ERMy(S).
3. For any h*, with probability of at least 1 — 6,
2 In (8/6
Lp(ERMy(S)) — Lp(h*) < 2R(LoHoS) + sey 2 ae).

m

26.1.1

26.1 The Rademacher Complexity 379

Proof First note that the random variable Repp(F, $) = suppex (Lp(h) — Ls(h))
satisfies the bounded differences condition of Lemma 26.4 with a constant 2c/m.
Combining the bounds in Lemma 26.4 with Lemma 26.2 we obtain that with
probability of at least 1— 6,

Repp(F, 8) < ERepp(F, 5) +ey/2BC/) <2E R(loHoS’) +e/2 CV)

The first inequality of the theorem follows from the definition of Repp(F, S$).
For the second inequality we note that the random variable R(¢ 0 H oS’) also

satisfies the bounded differences condition of Lemma 26.4 with a constant 2c/m.
Therefore, the second inequality follows from the first inequality, Lemma 26.4,
and the union bound. Finally, for the last inequality, denote hy = ERMy(S)
and note that
Lp(hs) — Lp(h*)

= Lp(hs) — Ls(hs) + Ls(hs) — Ls(h*) + Ls(h*) — Lp(h*)

< (Lp(hg) — Ls(hs)) + (Ls(h*) — Lp(h*)). (26.10)
The first summand on the right-hand side is bounded by the second inequality of

the theorem. For the second summand, we use the fact that h* does not depend
on S; hence by using Hoeffding’s inequality we obtain that with probaility of at

least 1 — 6/2,
Ls(h*) —Lp(h*) < oy ne) (26.11)

Combining this with the union bound we conclude our proof.

The preceding theorem tells us that if the quantity R(¢oH0S) is small then it
is possible to learn the class H using the ERM rule. It is important to emphasize
that the last two bounds given in the theorem depend on the specific training

set S. That is, we use S both for learning a hypothesis from H as well as for
estimating the quality of it. This type of bound is called a data-dependent bound.

Rademacher Calculus

Let us now discuss some properties of the Rademacher complexity measure.
These properties will help us in deriving some simple bounds on R(¢0 Ho S) for
specific cases of interest.

The following lemma is immediate from the definition.

LEMMA 26.6 For any ACR", scalar c € R, and vector agp € R™, we have
R({ca+ao:a€ A}) < |e] R(A).

The following lemma tells us that the convex hull of A has the same complexity

as A.

380

Rademacher Complexities

LEMMA 26.7. Let A be a subset of R™ and let A’ =

N,Vj,a® € A,a; > 0, |lal]) = 1}. Then,

(Opi aja) (Ne

R(A’) = R(A).

Proof The main idea follows from the fact that for any vector v we have

Ya

a20:jah= 14

Therefore,

mR(A')=E — sup

fF a>0:\\a||;=1a

=E sup
F a>0:\|a||1= 15
m
= Esup OjQ;
FacAiay

=mR(A),

and we conclude our proof.

The next lemma, due to Massart, states that the Rademacher complexity o:

Uj = max Uj.

N

» aj op) oja\?

a) 47

a finite set grows logarithmically with the size of the set.

LEMMA 26.8 (Massart lemma) Let A =
in R™. Definea= x oN aj. Then,

{ai,...,an} be a finite set of vectors

2 log(N
R(A) < magia al W228).

Proof Based on Lemma 26.6, we can assume without loss of generality that:
a= 0. Let A > 0 and let A’ = {Aaj,..., Aa}. We upper bound the Rademacher

complexity as follows:

mR(A’) = E B [inaxto, a) =

<E
o

Se (o,a)

< log (z
o

= log (= I[= ) ;
acA’ i=l

where the last equality occurs because t
dent. Next, using Lemma A.6 we have thi

log (= elt) }
aca’

acA’ 4

E [ioe (sax elt “)]
o ac

}) // Jensen’s inequality

he Rademacher variables are indepen-
at for all a; € R,

Eet% =
oi 2

exp(a;) + exp(—ai)

< exp(a7/2),

26.1 The Rademacher Complexity 381

and therefore

2

mR(A’) < log (= [|e (3)) = log (= exp (si?)
ac€A/ i=l acA’

. no. 2 _ LAr . 2
< tog (Amex exp(lal?/2)) =los(|4')) + max? /2)

Since R(A) = ¢R(A’) we obtain from the equation that

 log(|Al) +9? maxaca((al?/2)
~ Am ,

R(A)

Setting A = \/2 log(|A|)/maxaea |lal|? and rearranging terms we conclude our

proof.

The following lemma shows that composing A with a Lipschitz function does
not blow up the Rademacher complexity. The proof is due to Kakade and Tewari.

LEMMA 26.9 (Contraction lemma) For each i € [m], let 6; : R > R be a p-
Lipschitz function, namely for all a, € R we have |¢;(a) — ¢;(8)| < pla — AI.
Fora € R™ let b(a) denote the vector (¢1(a1),.--,¢m(Ym)). Let PoA = {P(a) :
a € A}. Then,

R(po A) < pR(A).

Proof For simplicity, we prove the lemma for the case p = 1. The case p #
1 will follow by defining ¢! = 46 and then using Lemma 26.6. Let A; =
{(a1,---,@i-1, 0;(@;), Qi41,---,@m) : a € A}. Clearly, it suffices to prove that
for any set A and all i we have R(A;) < R(A). Without loss of generality we will
prove the latter claim for i = 1 and to simplify notation we omit the subscript
from ¢. We have

QE

mR(A;) =E [sp Yan
1

acAi j=
m
= E|supoid(ai) + iQ;
m m
== E sup | d(a1) + Ss oja; | + sup | —¢(a1) + Ss OiQj
2 02,.,0m aca = acd =
m m
=- E s — ¢(a i 4a,
Boa nom {ate a Hai) +> Joa + D7 ova
, i=2 i=2
m m
<.-= E sup ay —a4|+ oja; + aja’), 26.12
Fon na oe, (In —ail+Soom+ Sonat]. naa)
where in the last inequality we used the assumption that ¢ is Lipschitz. Next,
we note that the absolute value on |a; — aj| in the preceding expression can


382

26.2

Rademacher Complexities

be omitted since both a and a’ are from the same set A and the rest of the
expression in the supremum is not affected by replacing a and a’. Therefore,

m m
sup (« —a,t+ Ss oa, + Yat) : (26.13)
i=2 i=2

mR(A\) <

a,a’cA

But, using the same equalities as in Equation (26.12), it is easy to see that the
right-hand side of Equation (26.13) exactly equals m R(A), which concludes our
proof.

Rademacher Complexity of Linear Classes

In this section we analyze the Rademacher complexity of linear classes. To sim-
plify the derivation we first define the following two classes:

Hy = {x (w,x): |lwli <1}, He = {x (w,x): |[wll2 < 1}. (26.14)

The following lemma bounds the Rademacher complexity of Hz. We allow
the x; to be vectors in any Hilbert space (even infinite dimensional), and the
bound does not depend on the dimensionality of the Hilbert space. This property
becomes useful when analyzing kernel methods.

LEMMA 26.10 Let S = (x1,...,Xm) be vectors in a Hilbert space. Define: Hz 0
S = {((w,x1),---, (w,Xm)) : ||w|l2 <1}. Then,
R(Haos) < maxillxile

vm
Proof Using Cauchy-Schwartz inequality we know that for any vectors w, v we
have (w,v) < ||w]| ||v||. Therefore,

mR(Hz 0 S') = sup Yon (26.15)
[ach2oS j=]

{e

m

sup Ss oi(w, »)|

| w:|lw||<1 4

{e

r m
= sup (w, Ss ve

7 [willwi|<t Gy
m

<E | Sooo :
L i=l

Next, using Jensen’s inequality we have that

a\ 1/2 27\ 1/2
| “s
o
2

m

» OiXi
i=1

(26.16)

y O7X;j

i=l

E
o

IA
ics}

i=1 2 2

26.3

26.3 Generalization Bounds for SVM 383

Finally, since the variables o1,..., Om are independent we have

m

| Saente] =B] Dowstsi
i=l ij

E
o

m

= So (i, x3) E[oi9j] + (i, x:) E [03]
iAj i=1

=P [pxi|3 < m mare.
i=l

Combining this with Equation (26.15) and Equation (26.16) we conclude our
proof.

Next we bound the Rademacher complexity of H1 0 S.

LEMMA 26.11 Let S = (x1,...,Xm) be vectors in R”. Then,

2 log (2
R(H1 08) < max ||x;lloo 4/2282”),
i m
Proof Using Holder’s inequality we know that for any vectors w,v we have
(w,v) < ||w]l1 |||. Therefore,

m
mR(H,0S)=E} sup Se oii
& |acHios iy

m

sup Ss oi(w, x)|

Lw:llwlla<1 jay

{e

m
= E sup mona

[ w:lwl]1 <1

&

<E I ae . (26.17)
L i=l

For each j € [n], let vj = (@1,;,..., 0m) € R™. Note that ||v,j|]2 < /m max; ||x;|o0-
Let V = {v1,.--, Wn, -V1,---;—Vn}. The right-hand side of Equation (26.17) is
m R(V). Using Massart lemma (Lemma 26.8) we have that

RV) < max |xilloo V2 log(2n)/m,

which concludes our proof.

Generalization Bounds for SVM

In this section we use Rademacher complexity to derive generalization bounds
for generalized linear predictors with Euclidean norm constraint. We will show
how this leads to generalization bounds for hard-SVM and soft-SVM.

384

Rademacher Complexities

We shall consider the following general constraint-based formulation. Let H =
{w : ||w||2 < B} be our hypothesis class, and let Z = X x Y be the examples
domain. Assume that the loss function ¢: H x Z > R is of the form

e(w, (x, y)) = o((w.x), 9). (26.18)

where ¢: R x Y > Ris such that for all y € Y, the scalar function a +> ¢(a, y)
is p-Lipschitz. For example, the hinge-loss function, £(w, (x, y)) = max{0,1—
y(w,x)}, can be written as in Equation (26.18) using ¢(a,y) = max{0,1 —

ya}, and note that @ is 1-Lipschitz for all y € {+1}. Another example is the
absolute loss function, £(w, (x, y)) = |(w,x) — y|, which can be written as in
Equation (26.18) using $(a,y) = |a — y|, which is also 1-Lipschitz for all y € R.

The following theorem bounds the generalization error of all predictors in H
using their empirical error.

THEOREM 26.12 Suppose that D is a distribution over X x Y such that with
probability 1 we have that ||x|lp < R. Let H = {w : ||wll2 < B} and let
€:Hx Z —> R be a loss function of the form given in Equation (26.18)
such that for ally € Y, a ++ d(a,y) is a p-Lipschitz function and such that
maxX,e[—BR,BR) |P(a,y)| <c. Then, for any 5 € (0,1), with probability of at least
1 —6 over the choice of an i.i.d. sample of size m,

2pBR 21n(2/5)
vm 7 Vm
Proof Let F = {(x,y) 4 $((w,x),y) : w € H}. We will show that with

probability 1, R(Fo S) < pBR/,\/m and then the theorem will follow from
Theorem 26.5. Indeed, the set F'o S can be written as

VweH, Lp(w) < Ls(w)+

FoS = {(¢((w,x1),y1),-+-,6((W, Xm), Ym)) sw EH},

and the bound on R(F0S) follows directly by combining Lemma 26.9, Lemma 26.

and the assumption that ||x||2 < R with probability 1.

We next derive a generalization bound for hard-SVM based on the previous

theorem. For simplicity, we do not allow a bias term and consider the hard-SVM

problem:

argmin ||w||?s.t.. Vi, yi(w, xi) >1 (26.19)
w

THEOREM 26.13 Consider a distribution D over X x {+1} such that there exists
some vector w* with P(x,y)~ply(w*,x) > 1] = 1 and such that ||x|/2 < R with
probability 1. Let wg be the output of Equation (26.19). Then, with probability
of at least 1 — 6 over the choice of S ~~ D™, we have that

2In(2/6)

| 2RIW' ls iw
veto # sign((ws,x))] < Vm (1+ Rilw*||) mm


26.3 Generalization Bounds for SVM 385

Proof Throughout the proof, let the loss function be the ramp loss (see Sec-
ion 15.2.3). Note that the range of the ramp loss is [0,1] and that it is a
-Lipschitz function. Since the ramp loss upper bounds the zero-one loss, we
have that

Ply Asign((ws,x))] < Lo ws).
(x,y)~D
Let B = ||w*||2 and consider the set H = {w : ||w||2 < B}. By the definition of
hard-SVM and our assumption on the distribution, we have that ws € H with
probability 1 and that Ls(wg) = 0. Therefore, using Theorem 26.12 we have
hat

2BR . [2in(2/5)

Lp(ws) < Ds(ws) + a

Remark 26.1 Theorem 26.13 implies that the sample complexity of hard-SVM
RP \w" |?

. Using a more delicate analysis and the separability assump-
2 ay 112
tion, it is possible to improve the bound to an order of Pier.

grows like

The bound in the preceding theorem depends on ||w*||, which is unknown.
In the following we derive a bound that depends on the norm of the output of
SVM; hence it can be calculated from the training set itself. The proof is similar
to the derivation of bounds for structure risk minimization (SRM).

THEOREM 26.14 Assume that the conditions of Theorem 26.13 hold. Then,
with probability of at least 1—6 over the choice of S~D™, we have that

Fal i 4R\|ws|| In(41282(lws|D oa wsll))
. g, <
«ol sign((ws,x))] < vm m

Proof For any integer i, let By = 2', Hi = {w : ||w|| < Bi}, and let 6; = 3s.
Fix i, then using Theorem 26.12 we have that with probability of at least 1— 4;

2B,R  [2in(2/6i)
vm m

Applying the union bound and using )>?°, 6; < 6 we obtain that with probability
of at least 1—6 this holds for all i. Therefore, for all w, if we let i = [log,(||w]|)]

then w € Hi, B; < 2||w||, and 2? = i)" < (toga (hw)? Therefore,

Vw Ee Hi, Lp(w) < Ls(w) +

2BiR 21n(2/65;)
Vm m

Aljw||R yj Leeczaltr)) + 60/5)
m7 ~

In particular, it holds for wg, which concludes our proof.

Lp(w) < Ls(w) +

< Ls(w) 4


386

26.4

26.5

Rademacher Complexities

Remark 26.2 Note that all the bounds we have derived do not depend on the
dimension of w. This property is utilized when learning SVM with kernels, where
the dimension of w can be extremely large.

Generalization Bounds for Predictors with Low ¢, Norm

In the previous section we derived generalization bounds for linear predictors
with an ¢)-norm constraint. In this section we consider the following general ¢-
norm constraint formulation. Let H = {w : ||w||1 < B} be our hypothesis class,
and let Z = X x Y be the examples domain. Assume that the loss function,
¢:Hx Z—R, is of the same form as in Equation (26.18), with 6: Rx YR
being p-Lipschitz w.r.t. its first argument. The following theorem bounds the
generalization error of all predictors in H using their empirical error.

THEOREM 26.15 Suppose that D is a distribution over X x Y such that with
probability 1 we have that ||x||. < R. Let H = {w € R¢: ||wl], < B} and
let £: Hx Z—>R be a loss function of the form given in Equation (26.18)
such that for ally € Y, a+ ¢(a,y) is an p-Lipschitz function and such that
max,e[—BR,BR) |P(a,y)| <c. Then, for any 5 € (0,1), with probability of at least
1 —6 over the choice of an i.i.d. sample of size m,

VweH, Lp(w) < Ls(w) 4 appr Hd) ; of ne).

Proof The proof is identical to the proof of Theorem 26.12, while relying on

Lemma 26.11 instead of relying on Lemma 26.10.

It is interesting to compare the two bounds given in Theorem 26.12 and The-
orem 26.15. Apart from the extra log(d) factor that appears in Theorem 26.15,
both bounds look similar. However, the parameters B, R have different meanings
in the two bounds. In Theorem 26.12, the parameter B imposes an 2 constraint
on w and the parameter R captures a low 2-norm assumption on the instances.
In contrast, in Theorem 26.15 the parameter B imposes an ¢) constraint on w
(which is stronger than an ¢2 constraint) while the parameter R captures a low
é4.-norm assumption on the instance (which is weaker than a low ¢j-norm as-
sumption). Therefore, the choice of the constraint should depend on our prior
knowledge of the set of instances and on prior assumptions on good predictors.

Bibliographic Remarks

The use of Rademacher complexity for bounding the uniform convergence is
due to (Koltchinskii & Panchenko 2000, Bartlett & Mendelson 2001, Bartlett
& Mendelson 2002). For additional reading see, for example, (Bousquet 2002,
Boucheron, Bousquet & Lugosi 2005, Bartlett, Bousquet & Mendelson 2005).

26.5 Bibliographic Remarks 387

Our proof of the concentration lemma is due to Kakade and Tewari lecture
notes. Kakade, Sridharan & Tewari (2008) gave a unified framework for deriving
bounds on the Rademacher complexity of linear classes with respect to different
assumptions on the norms.

27

27.1

27.1.1

Covering Numbers

In this chapter we describe another way to measure the complexity of sets, which
is called covering numbers.

Covering

DEFINITION 27.1 (Covering) Let ACR" be a set of vectors. We say that A
is r-covered by a set A’, with respect to the Euclidean metric, if for all a € A
there exists a’ € A’ with ||a —a’|| < r. We define by N(r, A) the cardinality of
the smallest A’ that r-covers A.

Example 27.1 (Subspace) Suppose that AC R™, let c = maxacea |lal|, and as-
sume that A lies in a d-dimensional subspace of R™. Then, N(r, A) < (2cVd/r)¢.
To see this, let vi,...,vVa be an orthonormal basis of the subspace. Then, any
a € Acan be written as a = a av; with |lalloc < |lall2 = |lall2 < c. Let
e € R and consider the set

d
A= {dem : Vi, a cle nete notte,

i=l

Given a€ Ast. a= 3°“, av; with |lal|. <c, there exists a’ € A’ such that
Ja all? = Ie avi? <2 Sli? sed
i i

Choose ¢ = r/Vd; then ||a—a’|| <r and therefore A’ is an r-cover of A. Hence,

N(r, A) <A) = (*)" = (4).

r

Properties

The following lemma is immediate from the definition.

LEMMA 27.2. For any ACR", scalar c > 0, and vector aj € R™, we have
Vr >0, N(r, {ca+ao:a€ A}) < N(cr, A).

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.
Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

27.2

27.2 From Covering to Rademacher Complexity via Chaining 389

Next, we derive a contraction principle.

LEMMA 27.3 For each i € [ml, let “ : R > R be a p-Lipschitz function;
namely, for all a,8 € R we have |¢;(a) — ¢:(8)| < pla — B|. For a € R™ let
(a) denote the vector (¢1(a1),..-, oy Let po A= {G(a):a€ A}. Then,

N(pr,@0 A) < N(r, A).

Proof Define B = @o A. Let A’ be an r-cover of A and define B’ = go A’.
Then, for all a € A there exists a’ € A’ with ||a—a’|| < r. So,

l(a) — P(a)\)? = Silas) — di(ai))? < La ai)’ < (pr).

i

Hence, B’ is an (pr)-cover of B.

From Covering to Rademacher Complexity via Chaining

The following lemma bounds the Rademacher complexity of A based on the
covering numbers N(r,A). This technique is called Chaining and is attributed
to Dudley.

LEMMA 27.4 Let c= ming maxaca ||a— all. Then, for any integer M > 0,

a +

R(A) < eye * flog(N(c2-*, A).

Proof Let a be a minimizer of the objective function given in the definition
of c. On the basis of Lemma 26.6, we can analyze the Rademacher complexity
assuming that a = 0.

Consider the set By = {0} and note that it is a c-cover of A. Let By,..., By
be sets such that each B, corresponds to a minimal (¢2~*)-cover of A. Let

*

a* = argmax,.4(o,a) (where if there is more than one maximizer, choose one
in an arbitrary way, and if a maximizer does not exist, choose a* such that
(a,a*) is close enough to the supremum). Note that a* is a function of o. For
each k, let b) be the nearest neighbor of a* in By (hence b) is also a function

of 7). Using the triangle inequality,

|b —p&-D] < |b — a*|| + la* —b&-Y]] < c(27*§ 4 2- FY) = Be 27%,
For each k define the set

By = {(a—a’):a€ By, a’ € By_1, |la—a’|| < 3c27*}.

390

Covering Numbers

We can now write

1
R(A) = — E(o, a")
M
(o,a° —b™) + S(o,b — a)

k=1
1
< —B||lol| ja" — bo? i+ de sup (o,a)| .
m ach

Since ||o|| = Vm and |la* — b™|| < c2-™, the first summand is at most
Tm 2-™., Additionally, by Massart lemma,
™m

1
=—E
m

' =k. Ay2 : =k
1 sup (o.a) <302-bV2OKNER EAP) _ 69-1 Vlog (2% AD)
m acB, m m
Therefore,
an M
R(A) < mee * Nog(N(c2-*, A))

As a corollary we obtain the following:
LEMMA 27.5 Assume that there are a, > 0 such that for any k > 1 we have
\(log(N (c2-*, A)) < a + Bk.
Then,
R(A) < e (a+ 28).

Proof The bound follows from Lemma 27.4 by taking M — oo and noting that
SR 2 = Land OR, k2-* = 2.

Example 27.2 Consider a set A which lies in a d dimensional subspace of R™

d
and such that ¢ = maxaea ||a||. We have shown that N(r, A) < (224) . There-

fore, for any k,
\/log(N(c2-#, A)) < \/dlog (24+1Va)
< /dlog(2Vd) + Vkd

< /dlog(2Vd) + Vdk.
Hence Lemma 27.5 yields

R(A) < * ( yldtox(2va 4 2vil) of mo),


27.3 Bibliographic Remarks 391

27.3 Bibliographic Remarks

The chaining technique is due to Dudley (1987). For an extensive study of cover-
ing numbers as well as other complexity measures that can be used to bound the
rate of uniform convergence we refer the reader to (Anthony & Bartlet 1999).

28

28.1

Proof of the Fundamental Theorem
of Learning Theory

In this chapter we prove Theorem 6.8 from Chapter 6. We remind the reader
the conditions of the theorem, which will hold throughout this chapter: H is a
hypothesis class of functions from a domain ¥ to {0,1}, the loss function is the
0-1 loss, and VCdim(H) = d < oo.

We shall prove the upper bound for both the realizable and agnostic cases
and shall prove the lower bound for the agnostic case. The lower bound for the
realizable case is left as an exercise.

The Upper Bound for the Agnostic Case

For the upper bound we need to prove that there exists C' such that H is agnostic
PAC learnable with sample complexity

d+ In(1/6)

eS

u(e,d) <C

We will prove the slightly looser bound:

dlog(d/e) + In(1/6)_

my(e,d) <C a (28.1)

The tighter bound in the theorem statement requires a more involved proof, in
which a more careful analysis of the Rademacher complexity using a technique
called “chaining” should be used. This is beyond the scope of this book.

To prove Equation (28.1), it suffices to show that applying the ERM with a
sample size

32d 64d 8
m> 4 - log (S) +3" (8dlog(e/d) + 2log(4/d))

yields an e€, d-learner for H. We prove this result on the basis of Theorem 26.5.

Let (x1, y1),---; (Xm; Ym) be a classification training set. Recall that the Sauer-
Shelah lemma tells us that if VCdim(H) = d then

[{(h(x1)...-,h(Xm)) :h EH} < (ty"

Denote A = {(Un(x.)4yi)+-+ +> Un(xm)¢ym|) 12 € H}- This clearly implies that

ii < ("Py

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

28.2

28.2.1

28.2 The Lower Bound for the Agnostic Case 393

Combining this with Lemma 26.8 we obtain the following bound on the Rademacher

R(A) < [2dlowlem/ ay

Using Theorem 26.5 we obtain that with probability of at least 1 — 6, for every
hEH we have that

complexity:

8d log(em/d) ; v2 log(2/5)

m m

Lo(h) ~ Ls(h) < yf

Repeating the previous argument for minus the zero-one loss and applying the
union bound we obtain that with probability of at least 1 — 4, for every h € H
it holds that

8d log(em/d) ; Zee)

m m

IEo(h) ~ Est < yf

< ay) Sdloslem/) + 2log(4/5)

m

To ensure that this is smaller than € we need
4
m> 2° (8dlog(m) + 8dlog(e/d) + 2log(4/6)) .

Using Lemma A.2, a sufficient condition for the inequality to hold is that

e

32d 64d 8
m> 42 tog ( ) + (8dlog(e/d) + 21og(4/9)) .

The Lower Bound for the Agnostic Case

Here, we prove that there exists C such that H is agnostic PAC learnable with
sample complexity

d+ In(1/6)

—_,—.

€

my(e,6) > C

We will prove the lower bound in two parts. First, we will show that m(e,6) >
0.5 log(1/(46))/e?, and second we will show that for every 5 < 1/8 we have that
m(e, 6) > 8d/e?. These two bounds will conclude the proof.

Showing That m(e, 6) > 0.5 log(1/(46)) /e?

We first show that for any € < 1/2 and any 6 € (0,1), we have that m(e,d) >
0.5 log(1/(46))/e?. To do so, we show that for m < 0.5log(1/(4d))/e?, H is not
learnable.

Choose one example that is shattered by H. That is, let c be an example such

394 Proof of the Fundamental Theorem of Learning Theory

that there are hy,h_ € H for which hy(c) = 1 and h_(c) = —1. Define two
distributions, Dy. and D_, such that for b € {+1} we have

ltybe

Do({(z,y)}) -{ °

0 otherwise.

ift@=c

That is, all the distribution mass is concentrated on two examples (c,1) and
(c,-1), where the probability of (c,) is ibe and the probability of (c, —b) is

1-be
>

Let A be an arbitrary algorithm. Any training set sampled from Dy has the
form S' = (c,y1),---,(¢, Ym). Therefore, it is fully characterized by the vector

y = (y1,---,Ym) € {£1}™. Upon receiving a training set S, the algorithm A
returns a hypothesis h : X — {+1}. Since the error of A w.r.t. Dy only depends
on h(c), we can think of A as a mapping from {+1} into {+1}. Therefore,
we denote by A(y) the value in {+1} corresponding to the prediction of h(c),
where h is the hypothesis that A outputs upon receiving the training set S =
(6ur)s-+-+ (Ym):

Note that for any hypothesis h we have

1— h(c)be

Lp, (h) = By

In particular, the Bayes optimal hypothesis is hy and

e if Aly) #b

0 otherwise.

Lp,(A(y)) ~ Lp, (hp) = +A _ Be {

2 2

Fix A. For b € {+1}, let Y° = {y € {0,1}™: A(y) 4 b}. The distribution D,
induces a probability P, over {1}. Hence,

P[Lp,(A(y)) — Lp, (he) = | = Dy(¥") = Ss Prly|tacy)40}-
y

Denote N+ = {y : |{i: yi = 1}| > m/2} and N~ = {£1} \ N+. Note that for
any y € Nt we have P,[y] > P_[y] and for any y € N~ we have P_[y] > P,[y].

28.2 The Lower Bound for the Agnostic Case 395

Therefore,
jms P [Lp,(A(y)) — Ep, (he) = €
= mi Pyly]ti

pmax Do oly] Macy) 70]

y

1 1
> 5d Prlylawen + 5 0 Pb ltawe
y y

1 1
=5 De (Pelylthaoee + Plt) +5 DD (Pelyltaaen + P-bylthagye)
yeNt yeN-

1 1
25 DL Plage + Plage) + 3 LE (Pelyltaoyes + Pelyltagy 2)
yEeNn+ yeNn-
l 1
a) Ss Ply|+5 Ss Pyly) .
yeNt yeN-

Next note that Y)yey+ Ply] = Vyew- P+ly], and both values are the prob-
ability that a Binomial (m, (1 — €)/2) random variable will have value greater

than m/2. Using Lemma B.11, this probability is lower bounded by
1 ——————_—_.——.— 1 _——
5) (1- VI-e~Cme/1— 2p) > 5) (1- VI~exp-2me)) ;

where we used the assumption that e? < 1/2. It follows that if m < 0.5 log(1/(46)) /e?
then there exists b such that

P[Lp,(A(y)) — Ev, (ho) = €]

>5(1-vi- va) >,

where the last inequality follows by standard algebraic manipulations. This con-
cludes our proof.

28.2.2 Showing That m(c, 1/8) > 8d/e?

We shall now prove that for every ¢ < 1/(8V2) we have that m(e,6) > 8¢.

Let p = 8¢ and note that p € (0,1/V/2). We will construct a family of distri-
butions as follows. First, let C = {c1,...,ca} be a set of d instances which are
shattered by H. Second, for each vector (b1,...,ba) € {+1}", define a distribu-
tion Dy such that

1. itube if Fira =o,
Di{(ey)P=h 4 2 eee
o({()}) (i otherwise.

That is, to sample an example according to Dp, we first sample an element c; € C
uniformly at random, and then set the label to be 6; with probability (1+ p)/2
or —b; with probability (1 — p)/2.

It is easy to verify that the Bayes optimal predictor for Dy is the hypothesis

396

Proof of the Fundamental Theorem of Learning Theory

h € H such that h(c;) = b; for all i € [d], and its error is +52. In addition, for
any other function f : ¥ — {+1}, it is easy to verify that

En(f) = 1te Mie fle) Ab, 1=9 Hee ld fle) = md

Therefore,

[fi € [a] : f(ci) A bi}
p- i .

Lp,(f) ~ min Lp, (h) (28.2)

Next, fix some learning algorithm A. As in the proof of the No-Free-Lunch
theorem, we have that

Dube tary seBp [em.(ats)) ~ jain £o,(t)] (28.3)
2 Drbwteet}) sebe [zesta( S)) — main (28.4)
~ nua 5 ben le . Hes aid . SNe) # “A (28.5)
~ ty pont t(aiys sabe HASVe)Ab:): (28.6)

where the first equality follows from Equation (28.2). In addition, using the
definition of Dy, to sample S ~ Dy we can first sample (j1,..-, jm) ~ U({d])”
x, = c;,, and finally sample y, such that Ply, = b;,] = (1+ p)/2. Let us simplify
the notation and use y ~ b to denote sampling wang to Ply = b] = (1+,)/2.
Therefore, the right-hand side of Equation (28.6) equals

d
p
p E EE thacsye),)- 28.7
oe ay) puree) vny ny, HAG )e0) 4h (28.7)

We now proceed in two steps. First, we show that among all learning algorithms,
A, the one which minimizes Equation (28.7) (and hence also Equation (28.4))
is the Maximum-Likelihood learning rule, denoted Aj,;,. Formally, for each 3,
Am(S)(c;) is the majority vote among the set {y, : r € [m], 2, = c;}. Second,
we lower bound Equation (28.7) for Aart.

LEMMA 28.1 Among all algorithms, Equation (28.4) is minimized for A being
the Mazimum-Likelihood algorithm, Ayyy, defined as

Vi, Anx(S)(ci) = vn Ss r) .

Tl =Cj

Proof Fix some j € [{d]™. Note that given j and y € {+1}", the training set
S is fully determined. Therefore, we can write A(j,y) instead of A(S). Let us
also fix i € [d]. Denote b™ the sequence (b1,..., bi-1, bi41,---;bm)- Also, for any

28.2 The Lower Bound for the Agnostic Case 397

y € {+1}™, let y! denote the elements of y corresponding to indices for which
jr =i and let y~ be the rest of the elements of y. We have
E E c
BAU {EL} 4) Wren by, [A(S)(ci) Abi]
1

=5 > E YE PHO bil tyaGy)eade0
2 beqaay? WEED) 7

ary 1
= een PWS EE Ply" bltaGanceozea
b-iNU({£1} at 2 vt \o,efaty

The sum within the parentheses is minimized when A(j, y)(c;) is the maximizer
of P[y’|b;] over b; € {£1}, which is exactly the Maximum-Likelihood rule. Re-
peating the same argument for all i we conclude our proof.

Fix i. For every j, let ni(j) = {|t : je = i|} be the number of instances in which

the instance is c;. For the Maximum-Likelihood rule, we have that the quantity

E E
pou Cee1}4) Veg hb, HAare(S)(ei) Abi

is exactly the probability that a binomial (n;(j), (1 — )/2) random variable will
be larger than n;(j)/2. Using Lemma B.11, and the assumption p? < 1/2, we
have that

P[B > ni(3)/2| = ; (1 -Vi- ene") ;

We have thus shown that

d
p
= E E E hacsye
d > jr ([d])™ bLU ({£1} 4) Vryrvdj,. [A(S) (es) #4]

d
£ 7 _ Viney
2 2d 2 jaye (1 1 — e720? @)
d
p z _ -
= 2d 2 jauheaym (1 2Pni(5)) ;

where in the last inequality we used the inequality 1—e~* <a.
Since the square root function is concave, we can apply Jensen’s inequality to
obtain that the above is lower bounded by

1— , /2p? E AG]
( ° ae")

(1 - 2p?m/d)

(1- Vanja).

2

Xls

Nan
Ms iM

NID

398

28.3

Proof of the Fundamental Theorem of Learning Theory

As long as m < a this term would be larger than p/4.
In summary, we have shown that if m < ae then for any algorithm there
exists a distribution such that
— mi >
oB, [Eo(AlS)) ~ in Lo(0)] > 0
Finally, Let A = i (Lp(A(S)) —minnex Lp(h)) and note that A € [0,1] (see
Equation (28.5)). Therefore, using Lemma B.1, we get that

P[Lp(A(S)) ~ min Lp(h) >] =P [ > ‘] > E[A] — ;

p

IV
ALB

Choosing p = 8¢ we conclude that if m < sie then with probability of at least
1/8 we will have Lp(A(S)) — minney Lp(h) > €.

The Upper Bound for the Realizable Case

Here we prove that there exists C such that H is PAC learnable with sample
complexity
din(1/e) + In(1/6)

€

my(e,6) <C

We do so by showing that for m > camt/e+inG/s) H is learnable using the
ERM rule. We prove this claim based on the notion of e-nets.

DEFINITION 28.2 (cnet) Let Y be a domain. S$ C ¥ is an cnet for H Cc 2%
with respect to a distribution D over ¥ if

VheH: Dih)>e + hnS#O.

THEOREM 28.3. Let H C 2° with VCdim(H) = d. Fix € € (0,1), 6 € (0,1/4)

and let
16e 2
m> 8 (2atoe (“) + log (5)).
€ € 0)

Then, with probability of at least 1—6 over a choice of S ~D™ we have that S
is an e-net for H.

Proof Let

B={SCX: |S

=m, Ihe H,D(h) >€,hnS =O}
be the set of sets which are not e-nets. We need to bound P[S € B]. Define

Bl ={(5,T) CX : |S|=|T| =m, IhEH,D(h) > hNS =O, |TOh| > }.

28.3 The Upper Bound for the Realizable Case 399

Claim 1
P[S € B] < 2P[(S,T) € B’.
Proof of Claim 1: Since S and T are chosen independently we can write

P((S,T) € B= (sepa [tsryeny] = oom [Bo [tys.ry<o"] .

Note that ($,7) € B’ implies S € B and therefore ls. ryeB) = lys.ryeB sen);
which gives

P(S,T)€ B= EE. tis.rnea sen)

lise a] peym ls.r)eB"):

swbm
Fix some S. Then, either Ijgeg) = 0 or S € B and then Shs such that D(hg) > €
and |hg 1 S| = 0. It follows that a sufficient condition for (S,T) € B’ is that

|[Ohs| > $+. Therefore, whenever S' € B we have

1 > BP).
em ser] > ,BlITAbs|> ¥

But, since we now assume S$ € B we know that D(hs) = p > e. Therefore,
|T Nhg| is a binomial random variable with parameters p (probability of success
for a single try) and m (number of tries). Chernoff’s inequality implies

PllTAhs| < om) < eo map me—mp/2)" — enmp/2 < enme/2 < en dlog(1/5)/2 _ gd/2 <1/2.
Thus,
P\|TOhs|> 4) = 1-PlTohs| < $F) > 1-PllTNhs| < SF] > 1/2.

Combining all the preceding we conclude the proof of Claim 1.

Claim 2 (Symmetrization):

P[(S,T) € B)} < e-@"/4 ry4(2m).

Proof of Claim 2: To simplify notation, let a = me/2 and for a sequence A =
(@1,---,%2m) let Ap = (x1,.-.,2%m). Using the definition of B’ we get that

PiAc B= E,. max Trp(ny>¢ lijanao|=o) Hinnalzal

< Emax = Sal]:
< , E,,, max Ynnao|=o) Ljanal>o]

Now, let us define by H, the effective number of different hypotheses on A,
namely, Ha = {hN A:h€H }. It follows that

P[AcB< E. Max Tynrao|=o] Yjaral>o)

< aan Ss Lynn Ao|=0} Mjanal>a)-

heHa

Let J = {j C [2m] : |j] = m}. For any j € J and A = (21,...,%2m) define
Aj = (aj,,...,2;,,). Since the elements of A are chosen i.i.d., we have that
for any j € J and any function f(A, Ao) it holds that E4vp2m[f(A, Ao)] =


400

Proof of the Fundamental Theorem of Learning Theory

Ea~p2[f(A, Aj)]. Since this holds for any j it also holds for the expectation of
j chosen at random from J. In particular, it holds for the function f(A, Ao)
nen, Minndo|=0) Ljnnaj>o]- We therefore obtain that

P[AcEB)< E E Ss Uynna;|=o] Ljana|>aj

AND2m jo J
heHa

=, Bn Ss Yanal>o] Man ayl=0)-
heHa ~

Now, fix some A s.t. [2 A] > a. Then, Ej Ijaqa,|=o) is the probability that

when choosing m balls from a bag with at least a red balls, we will never choose

a red ball. This probability is at most
(1 _ a/(2m))™ = ( _ €/4)™ < enema
We therefore get that

PAEB]< ED Yoeemice m4 Ela,

AnD2m

Using the definition of the growth function we conclude the proof of Claim 2.
Completing the Proof: By Sauer’s lemma we know that 7,(2m) < (2em/d)?.
Combining this with the two claims we obtain that

P[S € B] < 2(2em/d)4e78"/4”
We would like the right-hand side of the inequality to be at most 6; that is,
2(2em/d)4 e~""/4 < 6.

Rearranging, we obtain the requirement.

4 4d 4
m > — (dlog(2em/d) + log(2/6)) log(m) + —(dlog(2e/d) + log(2/6).
€ € €
Using Lemma A.2, a sufficient condition for the preceding to hold is that

m> 16d log (~) + 8 (dlog(2e/d) + log(2/6).
€ € €

A sufficient condition for this is that
16d d 16
m> 16d log (~) + + (dlog(2e/d) + 4 log(2/5)
€ € €
16d 8d2e 8
= — { log — log(2/6
“(log ($52) ) + Stoxt2/s)

=o) se)

and this concludes our proof.


28.3.1

28.3 The Upper Bound for the Realizable Case 401

From e-Nets to PAC Learnability

THEOREM 28.4 Let H be a hypothesis class over X with VCdim(H) = d. Let
D be a distribution over X and let c € H be a target hypothesis. Fir €,5 € (0,1)
and let m be as defined in Theorem 28.3. Then, with probability of at least 1—6
over a choice of m i.i.d. instances from X with labels according to c we have that
any ERM hypothesis has a true error of at most e.

Proof Define the class H® = {cA h: h € H}, where cA h = (h\c)U(c\h). It is
easy to verify that if some A C ¥ is shattered by H then it is also shattered by H®
and vice versa. Hence, VCdim(H) = VCdim(H°). Therefore, using Theorem 28.3
we know that with probability of at least 1— 6, the sample S is an e-net for H°.
Note that Lp(h) = D(h Ac). Therefore, for any h € H with Lp(h) > € we have
that |(h A.c)NS| > 0, which implies that h cannot be an ERM hypothesis, which
concludes our proof.


29

29.1

Multiclass Learnability

In Chapter 17 we have introduced the problem of multiclass categorization, in
which the goal is to learn a predictor h : X — [k]. In this chapter we address PAC
learnability of multiclass predictors with respect to the 0-1 loss. As in Chapter 6,
the main goal of this chapter is to:

e Characterize which classes of multiclass hypotheses are learnable in the (mul-
ticlass) PAC model.

e Quantify the sample complexity of such hypothesis classes.

In view of the fundamental theorem of learning theory (Theorem 6.8), it is natu-
ral to seek a generalization of the VC dimension to multiclass hypothesis classes.

In Section 29.1 we show such a generalization, called the Natarajan dimension,
and state a generalization of the fundamental theorem based on the Natarajan
dimension. Then, we demonstrate how to calculate the Natarajan dimension of
several important hypothesis classes.

Recall that the main message of the fundamental theorem of learning theory

is that a hypothesis class of binary classifiers is learnable (with respect to the
0-1 loss) if and only if it has the uniform convergence property, and then it
is learnable by any ERM learner. In Chapter 13, Exercise 2, we have shown
that this equivalence breaks down for a certain convex learning problem. The
last section of this chapter is devoted to showing that the equivalence between
learnability and uniform convergence breaks down even in multiclass problems

with the 0-1 loss, which are very similar to binary clas

sification. Indeed, we

construct a hypothesis class which is learnable by a specific ERM learner, but
for which other ERM learners might fail and the uniform convergence property
does not hold.

The Natarajan Dimension

In this section we define the Natarajan dimension, which is a generalization of
the VC dimension to classes of multiclass predictors. Throughout this section,
let H be a hypothesis class of multiclass predictors; namely, each h € H is a
function from ¥ to [ki].

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

29.2

29.2.1

29.2 The Multiclass Fundamental Theorem 403

To define the Natarajan dimension, we first generalize the definition of shat-
tering.

DEFINITION 29.1 (Shattering (Multiclass Version)) We say that a set C C Y
is shattered by H if there exist two functions fo, fi : C — [k] such that

e For every x € C, fo(x) F fi(z).
e For every B C C, there exists a function h € H such that

Va € B,h(x) = fo(x) and Va € C'\ B, h(x) = fi (2).

DEFINITION 29.2 (Natarajan Dimension) The Natarajan dimension of H, de-
noted Ndim(H), is the maximal size of a shattered set CC ¥.

It is not hard to see that in the case that there are exactly two classes,
Ndim(H) = VCdim(H). Therefore, the Natarajan dimension generalizes the VC
dimension. We next show that the Natarajan dimension allows us to general-
ize the fundamental theorem of statistical learning from binary classification to
multiclass classification.

The Multiclass Fundamental Theorem

THEOREM 29.3 (The Multiclass Fundamental Theorem) There exist absolute
constants C',,C2 > 0 such that the following holds. For every hypothesis class H
of functions from &X to [k], such that the Natarajan dimension of H is d, we have

1. H has the uniform convergence property with sample complexity

C d+ log(1/6) dlog (k) + log(1/6)
1 > eo.

UC
e < my (e, 6) < Cy 2

€
2. H is agnostic PAC learnable with sample complexity

C d+ log(1/65) dlog (k) + log(1/6)
1 ee.

< my(€,) < C2

€
3. H is PAC learnable (assuming realizability) with sample complexity
d+log(1/6) _ dlog (£4) + log(1/8)

A S mye, 0) S Cg.

C1

On the Proof of Theorem 29.3

The lower bounds in Theorem 29.3 can be deduced by a reduction from the
binary fundamental theorem (see Exercise 5).

The upper bounds in Theorem 29.3 can be proved along the same lines of the
proof of the fundamental theorem for binary classification, given in Chapter 28
(see Exercise 4). The sole ingredient of that proof that should be modified in a
nonstraightforward manner is Sauer’s lemma. It applies only to binary classes

and therefore must be replaced. An appropriate substitute is Natarajan’s lemma:

404

29.3

29.3.1

Multiclass Learnability

LEMMA 29.4 (Natarajan) [{H| < |A|NdimCO . K2Ndim(H) |

The proof of Natarajan’s lemma shares the same spirit of the proof of Sauer’s
lemma and is left as an exercise (see Exercise 3).

Calculating the Natarajan Dimension

In this section we show how to calculate (or estimate) the Natarajan dimen-
sion of several popular classes, some of which were studied in Chapter 17. As
these calculations indicate, the Natarajan dimension is often proportional to the
number of parameters required to define a hypothesis.

One-versus-All Based Classes

In Chapter 17 we have seen two reductions of multiclass categorization to bi-
nary classification: One-versus-All and All-Pairs. In this section we calculate the
Natarajan dimension of the One-versus-All method.

Recall that in One-versus-All we train, for each label, a binary classifier that
distinguishes between that label and the rest of the labels. This naturally sug-
gests considering multiclass hypothesis classes of the following form. Let Hpin C
{0,1}¥ be a binary hypothesis class. For every h = (hi,-.., le) € (Hpin)” define
T(h): X > [k] by

T(h)(x) = argmax h;(z).
ie [Kk]
If there are two labels that maximize h;(x), we choose the smaller one. Also, let
Hy ={T(h) + hee (in) }-

What “should” be the Natarajan dimension of Heovake Intuitively, to specify a

hypothesis in Hpin we need d = VCdim(Hpin) parameters. To specify a hypothe-
sis in Hoya
should suffice. The following lemma establishes this intuition.

, we need to specify k hypotheses in Hpin. Therefore, kd parameters

LEMMA 29.5 If d= VCdim(Hpin) then
Ndim(HOY*) < 3kdlog (kd) .

bin

Proof Let C Cc & be a shattered set. By the definition of shattering (for mul-

ticlass hypotheses)
OvA,k
(non)
vA,k -

On the other hand, each hypothesis in He. is determined by using k hypothe-
ses from Hpin- Therefore,

He) |< | Abinde |
Cc

> Qlel,


29.3 Calculating the Natarajan Dimension 405

By Sauer’s lemma, | (Hbin)¢ | < |C|“. We conclude that

2s |(),| =

The proof follows by taking the logarithm and applying Lemma A.1.

OvA.k)

How tight is Lemma 29.5? It is not hard to see that for some classes, Ndim(H,;,,

can be much smaller than dk (see Exercise 1). However there are several natura
binary classes, Hpin (e.g., halfspaces), for which Ndim(HpY*"*) = Q(dk) (see
Exercise 6).

29.3.2 General Multiclass-to-Binary Reductions

The same reasoning used to establish Lemma 29.5 can be used to upper bound
he Natarajan dimension of more general multiclass-to-binary reductions. These
reductions train several binary classifiers on the data. Then, given a new in-
stance, they predict its label by using some rule that takes into account the
abels predicted by the binary classifiers. These reductions include One-versus-
All and All-Pairs.

Suppose that such a method trains / binary classifiers from a binary class Hpin,
and r : {0,1}! — [k] is the rule that determines the (multiclass) label according
o the predictions of the binary classifiers. The hypothesis class corresponding
o this method can be defined as follows. For every h = (hi,-..,hi) € (Hin)!
define R(h) : & — [k] by

R(R)(x) = r(ha(2)

..,hi(a)).

Finally, let
bin = {R(h) +h © (Hoin)!}.
Similarly to Lemma 29.5 it can be proven that:
LEMMA 29.6 If d= VCdim(Hpin) then
Ndim(Hpin) < 31d log (Id) .

The proof is left as Exercise 2.

29.3.3 Linear Multiclass Predictors

Next, we consider the class of linear multiclass predictors (see Section 17.2). Let
W:X x [k] + R¢ be some class-sensitive feature mapping and let

Hy = {= + argmax(w, U(x,i)) : we e| . (29.1)
i€[k]

Each hypothesis in Hy is determined by d parameters, namely, a vector w €
R*. Therefore, we would expect that the Natarajan dimension would be upper
bounded by d. Indeed:

406

29.4

Multiclass Learnability

THEOREM 29.7 Ndim(Hw) <d.

Proof Let C C & be a shattered set, and let fo, fi : C — [k] be the two

functions that witness the shattering. We need to show that |C| < d. For every

x € C let p(x) = U(x, fo(x)) — U(a, fi(x)). We claim that the set p(C) we

{p(x) : x € C} consists of |C| elements (i.e., p is one to one) and is shattered
by the binary hypothesis class of homogeneous linear separators on R®,

H = {x4 sign((w,x)) : we R%}.

Since VCdim(H) = d, it will follow that |C| = |p(C)| < d, as required.
To establish our claim it is enough to show that |H,c)| = 2ICl, Indeed, given
a subset B C C, by the definition of shattering, there exists hg € Hw for which

Va € B,hp(«) = fo(x) and Va €C\ B,hp(x) = fila).
Let wg € R¢ be a vector that defines hg. We have that, for every x € B,
(w, U(x, fola))) > (w, (a, fulz))) > (w, p(x) > 0.
Similarly, for every x € C \ B,
(w, p(x)) < 0.

It follows that the hypothesis gz € H defined by the same w € R? label the
points in p(B) by 1 and the points in p(C \ B) by 0. Since this holds for every
B C C we obtain that |C| = |p(C)| and |H,(c)| = 2!C!, which concludes our
proof.

The theorem is tight in the sense that there are mappings V for which Ndim(Hw) =

Q(d). For example, this is true for the multivector construction (see Section 17.2

and the Bibliographic Remarks at the end of this chapter). We therefore con-
clude:

COROLLARY 29.8 Let ¥ = R” and let UV : X x [k] + R”* be the class sensitive
feature mapping for the multi-vector construction:

U(x, y) =[ 0,...,0, 1,...,%, 0,...,0 ].
VA Cea en
eERW-1)n eR” ER(E-v)n
Let Hy be as defined in Equation (29.1). Then, the Natarajan dimension of Hy
satisfies

(k-1)(n-1) < Ndim(Hy) < kn.

On Good and Bad ERMs

In this section we present an example of a hypothesis class with the property
that not all ERMs for the class are equally successful. Furthermore, if we allow
an infinite number of labels, we will also obtain an example of a class that is

29.4 On Good and Bad ERMs 407

learnable by some ERM, but other ERMs will fail to learn it. Clearly, this also
implies that the class is learnable but it does not have the uniform convergence
property. For simplicity, we consider only the realizable case.

The class we consider is defined as follows. The instance space ¥ will be any
finite or countable set. Let Py(4) be the collection of all finite and cofinite
subsets of X (that is, for each A € Py(&), either A or X \ A must be finite).
Instead of [k], the label set is Y = P(X) U {x}, where * is some special label.
For every A € P7(X) define ha : ¥ > Y by

co ee

Finally, the hypothesis class we take is
H= {ha : AE Py(&)}.

Let A be some ERM algorithm for H. Assume that A operates on a sample
labeled by ha € H. Since hy is the only hypothesis in H that might return
the label A, if A observes the label A, it “knows” that the learned hypothesis
is ha, and, as an ERM, must return it (note that in this case the error of the
returned hypothesis is 0). Therefore, to specify an ERM, we should only specify
the hypothesis it returns upon receiving a sample of the form

$= {(01,%),--5 (tms*)}.
We consider two ERMs: The first, Agooa, is defined by
Agood($) = ho:

that is, it outputs the hypothesis which predicts ‘*’ for every x € XY. The second
ERM, Abpaa; is defined by

Avad(S) = Rie, ccm }e*

The following claim shows that the sample complexity of Apag is about ||-times
larger than the sample complexity of Agooa. This establishes a gap between
different ERMs. If ¥ is infinite, we even obtain a learnable class that is not
learnable by every ERM.

CLAIM 29.9

1. Let e,5 > 0, D a distribution over X andha € H. Let S be an i.i.d. sample
consisting of m > + log (3) examples, sampled according to D and labeled by
ha. Then, with probability of at least 1— 4, the hypothesis returned by Agooa
will have an error of at most e.

2. There exists a constant a > 0 such that for every 0 < € < a there exists a

distribution D over X and ha € H such that the following holds. The hypoth-

[X|-1
6e

according to D and labeled by ha, will have error > € with probability > es,

esis returned by Apaa upon receiving a sample of sizem < ; sampled

408

29.5

Multiclass Learnability

Proof Let D be a distribution over ¥ and suppose that the correct labeling
is ha. For any sample, Agooa returns either hg or ha. If it returns h4 then its
true error is zero. Thus, it returns a hypothesis with error > € only if all the m
examples in the sample are from ¥ \ A while the error of hg, Lp(hg) = Pp[A],
is > «. Assume m > 4 log(+); then the probability of the latter event is no more
than (1—6)™ < e-*™ <6. This establishes item 1.

Next we prove item 2. We restrict the proof to the case that |V| = d < oo.
The proof for infinite ¥ is similar. Suppose that Y = {xo,...,va—1}-.

Let a > 0 be small enough such that 1 — 2e > e~*¢ for every € < a and fix

some € < a. Define a distribution on ¥ by setting P{ao] = 1 — 2e and for all
<i<d-1,Plx]= 7s. Suppose that the correct hypothesis is hg and let the

sample size be m. Clearly, the hypothesis returned by Ajaa will err on all the

examples from ¥ which are not in the sample. By Chernoft’s bound, if m < oan

hen with probability > e~ 3, the sample will include no more than a examples

rom . Thus the returned hypothesis will have error > e.

The conclusion of the example presented is that in multiclass classification,
he sample complexity of different ERMs may differ. Are there “good” ERMs
‘or every hypothesis class? The following conjecture asserts that the answer is

yes.

CONJECTURE 29.10 The realizable sample complexity of every hypothesis class
Hc [k\* is

mny(e.9) = 0 (SMD).

€

We emphasize that the O notation may hide only poly-log factors of €,6, and
Ndim(H), but no factor of k.

Bibliographic Remarks

The Natarajan dimension is due to Natarajan (1989). That paper also established
the Natarajan lemma and the generalization of the fundamental theorem. Gen-
eralizations and sharper versions of the Natarajan lemma are studied in Haussler
& Long (1995). Ben-David, Cesa-Bianchi, Haussler & Long (1995) defined a large
family of notions of dimensions, all of which generalize the VC dimension and
may be used to estimate the sample complexity of multiclass classification.

The calculation of the Natarajan dimension, presented here, together with
calculation of other classes, can be found in Daniely et al. (2012). The example
of good and bad ERMs, as well as conjecture 29.10, are from Daniely et al.
(2011).

29.6

29.6 Exercises 409

Exercises

1. Let d,k > 0. Show that there exists a binary hypothesis Hpin of VC dimension
d such that Ndim(HO%""*") = d.

2. Prove Lemma 29.6.

3. Prove Natarajan’s lemma.

Hint: Fix some x9 € 4. For i,j € [k], denote by Hj; all the functions f :
& \ {xo} — [k] that can be extended to a function in H both by defining
Ff (zo) = i and by defining f(x) = j. Show that |H| < |H.x\ {a9}! + Liz, (Hisl
and use induction.

4. Adapt the proof of the binary fundamental theorem and Natarajan’s lemma
to prove that, for some universal constant C > 0 and for every hypothesis
class of Natarajan dimension d, the agnostic sample complexity of H is

myles) < clos (2) + oa(t/5)

5. Prove that, for some universal constant C' > 0 and for every hypothesis class
of Natarajan dimension d, the agnostic sample complexity of 1 is

(ed) > ob t be(t/8) |
€
Hint: Deduce it from the binary fundamental theorem.
6. Let H be the binary hypothesis class of (nonhomogenous) halfspaces in R¢.

The goal of this exercise is to prove that Ndim(HO™*) > (d—1)- (k—1).
1. Let Haiscrete be the class of all functions f : [k — 1] x [d— 1] — {0,1} for
which there exists some ig such that, for every j € [d—1]

Vi < in, f(i, 7) = 1 while Vi > ig, f(i,j) =0.
Show that Ndim(HOYA*.) = (d— 1) - (k- 1).
2. Show that Haiscrete can be realized by H. That is, show that there exists
a mapping w: [k — 1] x [d—1] > R® such that
Haiscrote C {hoy : he H}.

Hint: You can take (i, j) to be the vector whose jth coordinate is 1, whose
last coordinate is i and the rest are zeros.
3. Conclude that Ndim(HO“*) > (d—1)-(k-1).

30

30.1

Compression Bounds

Throughout the book, we have tried to characterize the notion of learnability
using different approaches. At first we have shown that the uniform conver-
gence property of a hypothesis class guarantees successful learning. Later on we
introduced the notion of stability and have shown that stable algorithms are
guaranteed to be good learners. Yet there are other properties which may be
sufficient for learning, and in this chapter and its sequel we will introduce two
approaches to this issue: compression bounds and the PAC-Bayes approach.

In this chapter we study compression bounds. Roughly speaking, we shall see
that if a learning algorithm can express the output hypothesis using a small sub-
set of the training set, then the error of the hypothesis on the rest of the examples
estimates its true error. In other words, an algorithm that can “compress” its
output is a good learner.

Compression Bounds

To motivate the results, let us first consider the following learning protocol.
First, we sample a sequence of k examples denoted T. On the basis of these
examples, we construct a hypothesis denoted hr. Now we would like to estimate
the performance of hy so we sample a fresh sequence of m—k examples, denoted
V, and calculate the error of hr on V. Since V and T are independent, we
immediately get the following from Bernstein’s inequality (see Lemma B.10).

LEMMA 30.1 Assume that the range of the loss function is [0,1]. Then,

2Ly(hr)log(1/8) , Alog(1/é)
IV

<6.

P |Lp(hr) — Ly(hr) > V] |<

To derive this bound, all we needed was independence between T and V.
Therefore, we can redefine the protocol as follows. First, we agree on a sequence
of k indices I = (i1,...,i~) € [m]*. Then, we sample a sequence of m examples

rest of the examples in S'. Note that this protocol is equivalent to the protocol
we defined before — hence Lemma 30.1 still holds.

Applying a union bound over the choice of the sequence of indices we obtain
the following theorem.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

30.1 Compression Bounds 411

THEOREM 30.2 Let k be an integer and let B: Z* + H be a mapping from
sequences of k examples to the hypothesis class. Let m > 2k be a training set
size and let A: Z™ +H be a learning rule that receives a training sequence S'
of size m and returns a hypothesis such that A(S) = B(z;,,...,2i,) for some
(i1,--.,%%) € [m]*. Let V = {2; : 9 € (ia,..-,%4)} be the set of examples which
were not selected for defining A(S). Then, with probability of at least 1— 5 over
the choice of S we have

Lp(A(S)) < Lv(A(S)) + \/ Ev(ACs))

4k log(m/6) , 8klog(m/6)

m ‘ m :
Proof For any I € [mJ let hy = B(zi,,...,2,). Let n = m — k. Combining
Lemma 30.1 with the union bound we have

P fr € [m]* st. Lp(hz) — Lv (hr) > hv (hi) Festi) teat]

<¥v P |i) — (hn > [ee ow) text]
1é[m]*
<m*6.

Denote 5’ = m*6§. Using the assumption k < m/2, which implies that n =
m —k > m/2, the above implies that with probability of at least 1 — 6’ we have
that

Lp(A(S)) < Ly(A(S)) + [1y(a(s)) Beatie) ; Selostin/?)

which concludes our proof.

As a direct corollary we obtain:

COROLLARY 30.3 Assuming the conditions of Theorem 30.2, and further as-
suming that Ly(A(S)) = 0, then, with probability of at least 1—6 over the choice
of S we have
8k log(m/6d
Lp(a(s)) < “lesten/)

These results motivate the following definition:

DEFINITION 30.4 (Compression Scheme) Let H be a hypothesis class of
functions from ¥ to Y and let k be an integer. We say that H has a compression
scheme of size k if the following holds:

For all m there exists A: Z™ — [m]* and B: Z* + H such that for all h € H,
if we feed any training set of the form (21,h(x1)),...,(@m,h(%m)) into A and
then feed (x;,,h(xi,)),..-,(i,,h(vi,)) into B, where (i1,...,i,) is the output
of A, then the output of B, denoted h’, satisfies Ls(h’) = 0.

It is possible to generalize the definition for unrealizable sequences as follows.

412

30.2

30.2.1

30.2.2

Compression Bounds

DEFINITION 30.5 (Compression Scheme for Unrealizable Sequences)
Let H be a hypothesis class of functions from ¥ to Y and let k be an integer.
We say that H has a compression scheme of size k if the following holds:

For all m there exists A: Z — [m]* and B: Z* + H such that for all h € H,
if we feed any training set of the form (x1, y1),---,(@m,Ym) into A and then
feed (2, ,Yi,)s--+)(Vi,+Yi,) into B, where (i,,..., ix) is the output of A, then
the output of B, denoted h’, satisfies Lg(h’) < Lg(h).

The following lemma shows that the existence of a compression scheme for
the realizable case also implies the existence of a compression scheme for the
unrealizable case.

LEMMA 30.6 Let H be a hypothesis class for binary classification, and assume
it has a compression scheme of size k in the realizable case. Then, it has a
compression scheme of size k for the unrealizable case as well.

Proof Consider the following scheme: First, find an ERM hypothesis and denote
it by h. Then, discard all the examples on which h errs. Now, apply the realizable
compression scheme on the examples that have not been removed. The output of
the realizable compression scheme, denoted h’, must be correct on the examples
that have not been removed. Since h errs on the removed examples it follows
that the error of h’ cannot be larger than the error of h; hence h’ is also an ERM

hypothesis.

Examples

In the examples that follows, we present compression schemes for several hy-
pothesis classes for binary classification. In light of Lemma 30.6 we focus on the
realizable case. Therefore, to show that a certain hypothesis class has a com-
pression scheme, it is necessary to show that there exist A,B, and k for which

Lg(h’) =0.

Axis Aligned Rectangles

Note that this is an uncountable infinite class. We show that there is a simple
compression scheme. Consider the algorithm A that works as follows: For each
dimension, choose the two positive examples with extremal values at this dimen-
sion. Define B to be the function that returns the minimal enclosing rectangle.
Then, for k = 2d, we have that in the realizable case, Ls(B(A(S))) = 0.

Halfspaces

Let X = R¢ and consider the class of homogenous halfspaces, {x > sign((w,x)) :
we R4}.

30.2.3

30.2 Examples 413

A Compression Scheme:
W.1.0.g. assume all labels are positive (otherwise, replace x; by y;x;). The com-
pression scheme we propose is as follows. First, A finds the vector w which is

in the convex hull of {x1,...,Xm} and has minimal norm. Then, it represents it

as a convex combination of d points in the sample (it will be shown later that
his is always possible). The output of A are these d points. The algorithm B
receives these d points and set w to be the point in their convex hull of minimal
norm.
Next we prove that this indeed is a compression sceme. Since the data is

inearly separable, the convex hull of {xj,..., Xm} does not contain the origin.

Consider the point w in this convex hull closest to the origin. (This is a unique

point which is the Euclidean projection of the origin onto this convex hull.) We
1

claim that w separates the data.‘ To see this, assume by contradiction that

(w,x;) <0 for some i. Take w’ = ( a)w + ax; for a =r € (0,1).

Then w’ is also in the convex hull and

\|w'|? = (1 — a)? |||? + 0? |x|? + 2a(1 — a) (w, x:)
S (1 =a) ||? + 2? [77

[fll] wll? + [losell? wll?

(wi? + bal?
__ bel Ihwl?
Tw? + Ia
1

2
_ wie.
Iw Tepe +
< [lwl?,

which leads to a contradiction.

We have thus shown that w is also an ERM. Finally, since w is in the convex
hull of the examples, we can apply Caratheodory’s theorem to obtain that w is
also in the convex hull of a subset of d+ 1 points of the polygon. Furthermore,
the minimality of w implies that w must be on a face of the polygon and this

implies it can be represented as a convex combination of d points.

It remains to show that w is also the projection onto the polygon defined by the
d points. But this must be true: On one hand, the smaller polygon is a subset of
the larger one; hence the projection onto the smaller cannot be smaller in norm.
On the other hand, w itself is a valid solution. The uniqueness of projection

concludes our proof.

Separating Polynomials

Let 4 = R¢ and consider the class x +> sign(p(x)) where p is a degree r polyno-
mial.

1 Tt can be shown that w is the direction of the max-margin solution.

414

30.2.4

30.3

Compression Bounds

(

the monomials of x up to degree r. Therefore, the problem of constructing a com-

Note that p(x) can be rewritten as (w, a(x)) where the elements of ¢() are all
pression scheme for p(x) reduces to the problem of constructing a compression
scheme for halfspaces in R“’ where d' = O(d").

Separation with Margin

Suppose that a training set is separated with margin 7. The Perceptron algorithm
guarantees to make at most 1/7? updates before converging to a solution that
makes no mistakes on the entire training set. Hence, we have a compression
scheme of size k < 1/7”.

Bibliographic Remarks

Compression schemes and their relation to learning were introduced by Little-
stone & Warmuth (1986). As we have shown, if a class has a compression scheme
then it is learnable. For binary classification problems, it follows from the funda-
a finite VC dimension. The other
direction, namely, whether every hypothesis class of finite VC dimension has a

mental theorem of learning that the class hi

compression scheme of finite size, is an open problem posed by Manfred War-
muth and is still open (see also (Floyd 1989, Floyd & Warmuth 1995, Ben-David
& Litman 1998, Livni & Simon 2013).

31

31.1

PAC-Bayes

The Minimum Description Length (MDL) and Occam’s razor principles allow a
potentially very large hypothesis class but define a hierarchy over hypotheses and
prefer to choose hypotheses that appear higher in the hierarchy. In this chapter
we describe the PAC-Bayesian approach that further generalizes this idea. In
the PAC-Bayesian approach, one expresses the prior knowledge by defining prior
distribution over the hypothesis class.

PAC-Bayes Bounds

As in the MDL paradigm, we define a hierarchy over hypotheses in our class H.
Now, the hierarchy takes the form of a prior distribution over H. That is, we
assign a probability (or density if H is continuous) P(h) > 0 for each h € H
and refer to P(h) as the prior score of h. Following the Bayesian reasoning
approach, the output of the learning algorithm is not necessarily a single hy-
pothesis. Instead, the learning process defines a posterior probability over H,
which we denote by Q. In the context of a supervised learning problem, where
H contains functions from ¥ to Y, one can think of Q as defining a randomized
prediction rule as follows. Whenever we get a new instance x, we randomly pick
a hypothesis h € H according to Q and predict h(x). We define the loss of Q on
an example z to be
def

(Q,2) = E [e(h,2)}

By the linearity of expectation, the generalization loss and training loss of Q can

be written as
def def
Ip(Q)= ,E [Lp(h)] and Ls(Q)= E [Ls(h)).
hxQ hnQ

The following theorem tells us that the difference between the generalization

loss and the empirical loss of a posterior Q is bounded by an expression that

depends on the Kullback-Leibler divergence between Q and the prior distribu-

tion P. The Kullback-Leibler is a natural measure of the distance between two

distributions. The theorem suggests that if we would like to minimize the gen-
eralization loss of Q, we should jointly minimize both the empirical loss of Q
and the Kullback-Leibler distance between Q and the prior distribution. We will

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

416

PAC-Bayes

later show how in some cases this idea leads to the regularized risk minimization
principle.

THEOREM 31.1 Let D be an arbitrary distribution over an example domain Z.
Let H be a hypothesis class and let £: Hx Z — [0,1] be a loss function. Let P be
a prior distribution over H and let 6 € (0,1). Then, with probability of at least

1—6 over the choice of an i.i.d. training set S = {z,...,%m} sampled according
to D, for all distributions Q over H (even such that depend on S'), we have

D(Q||P) +Inm/6
2(m — 1)

Lp(Q) < Ls(Q) +
where
def
DQIP) ™ B LlnQ(h)/P(H))
is the Kullback-Leibler divergence.

Proof For any function f(S), using Markov’s inequality:

PIN(S) > = Bel > 4 < Ble).

Let A(h) = Lp(h) — Lg(h). We will apply Equation (31.1) with the function

(31.1)

f(8) =syp (20m —1) ,E (AC)? ~ DQIP))
We now turn to bound Es[ef(S)]. The main trick is to upper bound f(5) by
using an expression that does not depend on Q but rather depends on the prior
probability P. To do so, fix some S and note that from the definition of D(Q||P)
we get that for all Q,
2(m 1) ,B, (ACh)? ~ D(QIIP) = ,E [ime"P 0" PC) /Q(H)]
nw

hw

< In E [eX 20" P(h)/Q(h)]

= In E,[err-Van"), (31.2)

where the inequality follows from Jensen’s inequality and the concavity of the

log function. Therefore,

Ble < EE [eum-van"), (31.3)

The advantage of the expression on the right-hand side stems from the fact that
we can switch the order of expectations (because P is a prior that does not
depend on S$’), which yields

Ble! < Epler am), (31.4)

31.2

31.3

31.2 Bibliographic Remarks 417

Next, we claim that for all h we have Eg[e2-DA(H)”] < m. To do so, recall that
Hoeffding’s inequality tells us that

P[A(h) >< erm

This implies that Eg[e2"-Y4()"] < m (sce Exercise 1). Combining this with
Equation (31.4) and plugging into Equation (31.1) we get
Pif(s)zd < 4. (31.5)
s ef
Denote the right-hand side of the above 6, thus ¢ = In(m/6), and we therefore
obtain that with probability of at least 1 — 6 we have that for all Q

a(m ~ 1) ,B_(A(h))? ~ D(Q||P) < €=In(m/8).

Rearranging the inequality and using Jensen’s inequality again (the function x?
is convex) we conclude that

2
(8,400) < Bam? s MAORI?) is)

Remark 31.1 (Regularization) The PAC-Bayes bound leads to the following
learning rule:

Given a prior P, return a posterior Q that minimizes the function

D(Q\|P) + In m/s

Bs(Q) + 2(m—1)

(31.7)
This rule is similar to the regularized risk minimization principle. That is, we

jointly minimize the empirical loss of Q on the sample and the Kullback-Leibler
“distance” between Q and P.

Bibliographic Remarks

PAC-Bayes bounds were first introduced by McAllester (1998). See also (McAllester
1999, McAllester 2003, Seeger 2003, Langford & Shawe-Taylor 2003, Langford
2006).

Exercises

1. Let X be a random variable that satisfies PIX > «| < e72™ Prove that
E[e2™-D*"}] <m.

418 PAC-Bayes

2. e Suppose that H is a finite hypothesis class, set the prior to be uniform over
H, and set the posterior to be Q(hs) = 1 for some hg and Q(h) = 0 for
all other h € H. Show that

Ly(hs) < Lh) +f Ue) el)

Compare to the bounds we derived using uniform convergence.
e Derive a bound similar to the Occam bound given in Chapter 7 using the
PAC-Bayes bound

Appendix A Technical Lemmas

LEMMA A.l_ Leta>0. Then: x > 2alog(a) = x > alog(z). It follows that a
necessary condition for the inequality x < alog(x) to hold is that x < 2alog(a).

Proof First note that for a € (0, /e] the inequality > alog(x) holds uncon-
ditionally and therefore the claim is trivial. From now on, assume that a > /e.
Consider the function f(2) = 2 — alog(x). The derivative is f/(a) = 1 — a/z.
Thus, for z > a the derivative is positive and the function increases. In addition,

f(2alog(a)) = 2a log(a) — alog(2alog(a))
= 2alog(a) — alog(a) — alog(2log(a))
= alog(a) — alog(2log(a)).

Since a — 2log(a) > 0 for all a > 0, the proof follows.

LEMMA A.2. Leta > 1 andb> 0. Then: « > 4alog(2a)+2b > x > alog(x)+b.

Proof It suffices to prove that x > 4alog(2a) + 2b implies that both x >
2alog(x) and « > 2b. Since we assume a > 1 we clearly have that x > 2b.
In addition, since b > 0 we have that « > 4alog(2a) which using Lemma A.1

implies that 2 > 2alog(x). This concludes our proof.

LEMMA A.3 Let X be a random variable and x' € R be a scalar and assume
that there exists a > 0 such that for allt >0 we have P[|X —2"| > t] < 2e-?/@.
Then, E[|X —2x'|] < 4a.

Proof For alli = 0,1,2,... denote t; = ai. Since ¢; is monotonically increasing
we have that E[|X — 2’|] is at most 0°, t;P[|X — x'| > t,-1]. Combining this
with the assumption in the lemma we get that E[|X —2'|] < 2a 0%, ie GD,
The proof now follows from the inequalities

oo 5 oo
Dies Pies [rete < 184 10-7 <2.

i=l i=l 5

LEMMA A.4_ Let X be a random variable and x' € R be a scalar and assume
that there exists a > 0 and b > e such that for allt > 0 we have P[|X — 2’| >
i] <2beP/. Then, E[|X — x']] < a(2+ v/log(®)).

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

420

Technical Lemmas

Proof For alli = 0,1,2,... denote t; = a (i+ \/log(b)). Since t; is monotonically
increasing we have that

E[|X —2'l] < av/log(6) + $0 t; PIX — 2'| > ta).

i=1

Using the assumption in the lemma we have

oo oo
STU PIX —2'| > ta] < 2ab SG + Vlog(o))e“ V8)”

i=1 i=1
oo

<2ab [ xe (1) dy
1+,/log(b)

°° 2
=2ab | (y+ le ¥ dy
log(b)
°° 2
<4ab | ye " dy
v/ log(b)

bf-e]
=2ab |—e7
0) xm
=2ab/b=2a.

Combining the preceding inequalities we conclude our proof.

LEMMA A.5_ Let m,d be two positive integers such that d <m— 2. Then,

(0) (2°

Proof We prove the claim by induction. For d = 1 the left-hand side equals

k=0

1+m while the right-hand side equals em; hence the claim is true. Assume that
the claim holds for d and let us prove it for d+ 1. By the induction assumption
we have

(PY (oe (Sy ee)

(: (‘) ran)


Technical Lemmas 421

Using Stirling’s approximation we further have that

em\4 _(d q (m—d)
s T) (: (£) aime)
emy\4 , m—d
7) (: aap)
em\¢ d+1+(m-—d)/V2rd
7) : d+1
em\4 d+1+(m-—d)/2
< 7) d+1
emt get emi?
d d+1
em\t4 m
<(T) ar

where in the last inequality we used the assumption that d < m — 2. On the

other hand,
em \“1 em\4 em d a
d+1 d+1 \d+1

d em 1

‘d+1 (+1/d4

)
)
)

which proves our inductive argument.

LEMMA A.6 For alla € R we have

a —a
e+e 2.

Proof Observe that

n=0
Therefore,
et + e-4 _ > an
20 <> (2n)!
and
oO on
a2/2 a
° ~ u 2 nl
n=0

Observing that (2n)! > 2” n! for every n > 0 we conclude our proof.


Appendix B Measure Concentration

B.1

Let Z1,...,Zm be an i.i.d. sequence of random variables and let js be their mean.
The strong law of large numbers states that when m tends to infinity, the em-
pirical average, + ay Z;, converges to the expected value jz, with probability
1. Measure concentration inequalities quantify the deviation of the empirical
average from the expectation when m is finite.

Markov’s Inequality

We start with an inequality which is called Markov’s inequality. Let Z be a
nonnegative random variable. The expectation of Z can be written as follows:

0°

BlZ|= [Plz > alae. (B.1)
x=0

Since P[Z > a] is monotonically nonincreasing we obtain

a a

PZ > alde> [PZ > olde =a PIZ > a (B.2)

«=0

Va>0, E[Z| > /

2=0
Rearranging the inequality yields Markov’s inequality:
E[Z
Va>0, P[Z>a] < EZ) (B.3)
a
For random variables that take value in [0,1], we can derive from Markov’s
inequality the following.

LEMMA B.1_ Let Z be a random variable that takes values in [0,1]. Assume that
E[Z] = p. Then, for any a € (0,1),
~(1-
Piz >1-q> #2 0-9).
a
This also implies that for every a € (0,1),
P[Z>a)>5-* > pa.
l-a

Proof Let Y =1-— Z. Then Y is a nonnegative random variable with E[Y] =
1—E[Z] =1- 4. Applying Markov’s inequality on Y we obtain
< E{Y] _i- we

P[Z <1-a)/=P(l-Z>al)=PlY Sal< a a

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

B.2

B.3

B.2 Chebyshev’s Inequality 423

Therefore,

1- -1
P[Z>1—-qj>1—-- eh a ot

Chebyshev’s Inequality

Applying Markov’s inequality on the random variable (Z — E[Z])? we obtain
Chebyshev’s inequality:

Va>0, Bl|Z [Z|] > a) = P[(Z— B[Z))? > a’) <

where Var[Z] = E[(Z — E[Z])?] is the variance of Z.
Consider the random variable a ee Z;. Since Z1,..., Zm are i.i.d. it is easy
to verify that

fit —_ Var[Z;]
Var Peg = ee

Applying Chebyshev’s inequality, we obtain the following:

LEMMA B.2. Let Z1,...,Zm be a sequence of i.i.d. random variables and assume
that E[Z,] = ps and Var[Z,] < 1. Then, for any 6 € (0,1), with probability of at
m

least 1 — 5 we have
1 1
= SoZ, -p) </—.
m om
i=l

Proof Applying Chebyshev’s inequality we obtain that for all a > 0
Var[Z,] 1

1
P}j— Zi- < < :
Eps iTW > ay S maz ~ ma?

The proof follows by denoting the right-hand side 6 and solving for a.

The deviation between the empirical average and the mean given previously
decreases polynomially with m. It is possible to obtain a significantly faster

decrease. In the sections that follow we derive bounds that decrease exponentially
fast.

Chernoff’s Bounds

Let Z1,..., Zm, be independent Bernoulli variables where for every i, P(Z; = 1] =
pi and P{Z; = 0) = 1— p;. Let p = Oy", pi and let Z = STV", Z;. Using the

424

Measure Concentration

monotonicity of the exponent function and Markov’s inequality, we have that for

every t > 0
P[Z > (1+ 6)p] = Ple'? > e149?) < He . (B.5)
e€ P
Next,
Ble!”] = Efe!>:*] = El] [ e'”]
= Il Efe!*] by independence
i
=[] (ie! + pide’)
i
= Il (1+ pie — 1)
< Te“ using 1+ 2 < e”
i

= pXivile'-1)

= ep,
Combining the above with Equation (B.5) and choosing t = log(1+6) we obtain
LEMMA B.3_ Let Z1,..., Zm be independent Bernoulli variables where for every
i, P[Z; = 1) =p; and P[Z; = 0) =1—p;. Let p= oi", pi and let Z =O", Z;.
Then, for any 6 > 0,
PIZ > (1+ d)p] < eH hO?,
where
h(d) = (1 + 6) log(1 + 6) — 6.

Using the inequality h(a) > a?/(2 + 2a/3) we obtain

LEMMA B.4_ Using the notation of Lemma B.3 we also have
P[Z > (1+5)p] < eo? mT
For the other direction, we apply similar calculations:

Efe~'7]

P[Z < (1-8)p] = P[-Z > —(1—5)p] = Ple 4 > e-9)P] <
e- Sip

, (B6)

B.4

B.4 Hoeffding’s Inequality 425

and,

Ele~*7] _ Elet=: Zi) _ e{] e 4

= [[£e"”) by independence
i

= II (1+ pi(e* - 1))

< ll epile*-1) using 1 +2 < e”

_ ep

Setting t = — log(1 — 6) yields

EWP

—ph(—6)
dP] S Samana =

P[Z<(1
It is easy to verify that h(—d) > h(d) and hence

LEMMA B.5 Using the notation of Lemma B.3 we also have

52

P[Z <(1—d)p] < eT PMP) < eo PhO) < e278,

Hoeffding’s Inequality

LEMMA B.6 (Hoeffding’s inequality) Let Z1,..., Zm be a sequence of i.i.d.

random variables and let Z = +7", Z;. Assume that E[Z] = p and Pla <

i=

Z;, <b] =1 for every i. Then, for any € > 0
m

P([|asez—»
i=l

Proof Denote X; = Z; — E[Z;] and X = Pa >>; Xi. Using the monotonicity of
the exponent function and Markov’s inequality, we have that for every \ > 0

and e>0,

> | < 2exp (-2me?/(b— a)’).

PLX > e] = Ple’* > e] < e-* Ele).

Using the independence assumption we also have

Tes} _ [[#e*”"1.

By Hoeffding’s lemma (Lemma B.7 later), for every i we have

E[e*] =E

E[e*/™] < e Mae"

426

B.5

Measure Concentration

Therefore,

2 (b—a)? 2 (b—a)?

PIX >q<e* [le = pt ES

a

Setting \ = 4me/(b — a)? we obtain

2me2

P[X >eJ<e Go,

Applying the same arguments on the variable —X we obtain that P[X < —«] <

_ _2me?
e (-«)? | The theorem follows by applying the union bound on the two cases.

LEMMA B.7 (Hoeffding’s lemma) Let X be a random variable that takes values
in the interval [a,b] and such that E[X] = 0. Then, for every > 0,

2 (b—a)?

E[e*]<e— 5

Proof Since f(x) = e*” is a convex function, we have that for every a € (0,1),
and x € [a,b],

F(x) < af(a) + A a) f(b).
Setting a = #=* € [0,1] yields

.-b-« za
odv< ene ee,

~ b-a_ b-a
Taking the expectation, we obtain that
b-E[X] Elz] —a b a
EX] < ra _Nb _da _rb_
lel s b-a e b-a © ba. ba’ ,

where we used the fact that E[X] = 0. Denote h = \(b— a), p = 7%, and

L(h) = —hp + log(1 — p+ pe"). Then, the expression on the right-hand side o

the above can be rewritten as e/("), Therefore, to conclude our proof it suffices

to show that L(h) < am This follows from Taylor’s theorem using the facts:

L(0) = L'(0) =0 and L’(h) < 1/4 for all h.

Bennet’s and Bernstein’s Inequalities

Bennet’s and Bernsein’s inequalities are similar to Chernoft’s bounds, but they
hold for any sequence of independent random variables. We state the inequalities
without proof, which can be found, for example, in Cesa-Bianchi & Lugosi (2006).

LEMMA B.8 (Bennet’s inequality) Let Z,,...,Zm, be independent random vari-
ables with zero mean, and assume that Z; <1 with probability 1. Let

m

1
of > —) E27).
m i=l

B.5.1

B.5 Bennet’s and Bernstein’s Inequalities 427

Then for alle > 0,

P

7 > | < eomeh( aor),

i=l
where
h(a) = (1 +a) log(1 + a) — a.
By using the inequality h(a) > a?/(2 + 2a/3) it is possible to derive the
following:

LEMMA B.9 (Bernstein’s inequality) Let Z1,..., Zm, be i.i.d. random variables

with a zero mean. If for all i, P(|Z;| <M) =1, then for allt > 0:

P soz >t} <exp | — #2
pet) SOP \ SEZ? + Mt/3 J

i=1

Application

Bernstein’s inequality can be used to interpolate between the rate 1/e we derived
for PAC learning in the realizable case (in Chapter 2) and the rate 1/e? we derived
for the unrealizable case (in Chapter 4).

LEMMA B.10 Let £: Hx Z — [0,1] be a loss function. Let D be an arbitrary
distribution over Z. Fix some h. Then, for any 6 € (0,1) we have

1B, [rs(h) > both) yEz0) lost) | 2/5) <5
2Ls(h)log(1/d) | 4log(1/6)
2 P [zo > Ls(h) / > + ——— | <6

Proof Define random variables a1,..., am s.t. a; = C(h, 21) — Lp(h). Note that
E[a;] = 0 and that

E{a?] = E[¢(h, z:)?] — 2Lp(h) El€(h, 21)] + Lp(h)?
= Ele(h, 2i)"] — Lo(h)?
< E[é(h, z:)?]
< E[é(h, z:)| = Lo(h),

where in the last inequality we used the fact that ¢(h,z;:) € [0,1] and thus
L(h, z;)? < e(h, z:). Applying Bernsein’s inequality over the a;’s yields

m 2/9
P Is a; > J < exp (-sxan)

i=l
t?/2 d
/ ) def 6.

S exp (- mLp(h) +t/3

428

B.6

B.7

Measure Concentration

Solving for t yields
t?/2
—__—_~ = log(1/6
mLp(hy #473 ~ 84/9)

log (1/5) [eg + 2log(1/5) m Lp(h)

3 3?
<2 fest) + s/2log(1/5) m Lp(h)

Since 1 SY, a; = Ls(h)—Lp(h), it follows that with probability of at least 1—6,

Ls(h) ~ Ep(h) <2 28009), /?He8(/8) Poth),

which proves the first inequality. The second part of the lemma follows in a

similar way.

Slud’s Inequality

Let X be a (m,p) binomial variable. That is, X = 7", Z;, where each Z; is 1
with probability p and 0 with probability 1—p. Assume that p = (1—«)/2. Slud’s
inequality (Slud 1977) tells us that PLX > m/2] is lower bounded by the proba-
bility that a normal variable will be greater than or equal to \/me?/(1 — €?). The

following lemma follows by standard tail bounds for the normal distribution.

LEMMAB.11_ Let X be a(m,p) binomial variable and assume that p = (1—«)/2.
Then,

P[X > m/2] => ; (1 — V1 exp(—me?/(1 — 2) .

Concentration of \? Variables

Let X1,...,X, be k independent normally distributed random variables. That
is, for all i, X; ~ N(0,1). The distribution of the random variable X? is called
x? (chi square) and the distribution of the random variable Z = X? +---+ X?
is called y? (chi square with k degrees of freedom). Clearly, E[X?] = 1 and
E[Z] = k. The following lemma states that X? is concentrated around its mean.
LEMMA B.12_ Let Z ~ x7. Then, for all ¢ > 0 we have

P[Z < (1—6)k] < e4/8,

and for all € € (0,3) we have

PIZ > (1+e)k] se 8/6,

B.7 Concentration of x? Variables 429

Finally, for all € € (0,3),
P[(l-Qk<Z<(1+e)k] > 1-2-8",

Proof Let us write Z = Y*_, X? where X; ~ N(0,1). To prove both bounds
we use Chernoff’s bounding method. For the first inequality, we first bound
Ele~*i], where > 0 will be specified later. Since e~* < 1—a+ o for alla > 0
we have that

\
Ble *T] < 1-\ELX2] + 5 EIXt)

Using the well known equalities, E[X?] = 1 and E[X#] = 3, and the fact that
1—a<e~“ we obtain that

Ele*7] < 1-A4 380? <2”,
Now, applying Chernoff’s bounding method we get that
P[-Z>-(1— ek] =P le > eK)
<e(l-9 B [e-*7]
= e(l-eka (E [e*])"
< ello) kA eT kt gk
= echt SRM
Choose \ = €/3 we obtain the first inequality stated in the lemma.

For the second inequality, we use a known closed form expression for the
moment generating function of a x? distributed random variable:

V<}, Ele] = (1-2a)*?. (B.7)
On the basis of the equation and using Chernoff’s bounding method we have
P[Z>(1+ 0k) =P [ed > crow]
< eO+9 BL eAZ]
=e (49K (7 9) 7K?

< eT te)kX okX — peka

where the last inequality occurs because (1 — a) < e~*. Setting \ = €/6 (which
is in (0,1/2) by our assumption) we obtain the second inequality stated in the
lemma.

Finally, the last inequality follows from the first two inequalities and the union
bound.


Appendix C Linear Algebra

C1

Basic

In this
spaces.

Definitions

chapter we only deal with linear algebra over finite dimensional Euclidean
We refer to vectors as column vectors.

Given two d dimensional vectors u,v € R¢, their inner product is

(u,v) = Ss UjV;-

i=l

The Euclidean norm (a.k.a. the ¢2 norm) is ||u|] = \/(u, a). We also use the £;
norm, ||ul|; = ean ju;| and the @ norm |lul|., = max; |w;|.

A subspace of R¢ is a subset of R¢ which is closed under addition and scalar

multiplication. The span of a set of vectors uj,..., Ux is the subspace containing

all vectors of the form

where

A se

span of

span 0}

y ju;
i=l

or alli, a; € R.
of vectors U = {u;,...,u,} is independent if for every i, u; is not in the

;U,. We say that U spans a subspace V if V is the
the vectors in U. We say that U is a basis of V if it is both independent

and spans V. The dimension of V is the size of a basis of V (and it can be verified

that al
alli Fé

and if

bases of V have the same size). We say that U is an orthogonal set if for
Jj, (ui, uj) = 0. We say that U is an orthonormal set if it is orthogonal
or every i, ||u;|| = 1.

Given a matrix A € R"“, the range of A is the span of its columns and the

null space of A is the subspace of all vectors that satisfy Au = 0. The rank of A

is the
The
equals

imension of its range.

transpose of a matrix A, denoted A', is the matrix whose (i,j) entry

he (j,i) entry of A. We say that A is symmetric if A= A‘.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

C.2

C.3

C.4

C.2 Eigenvalues and Eigenvectors 431

Eigenvalues and Eigenvectors

Let A € R% be a matrix. A non-zero vector u is an eigenvector of A with a
corresponding eigenvalue A if

Au = Au.

THEOREM C.1 (Spectral Decomposition) If A € R&* is a symmetric matrix of
rank k, then there exists an orthonormal basis of R¢, w1,..., Ua, such that each
u; is an eigenvector of A. Furthermore, A can be written as A = ean Aju; ,
where each i; is the eigenvalue corresponding to the eigenvector u;. This can
be written equivalently as A= UDU", where the columns of U are the vectors
uy,...,Ug, and D is a diagonal matrix with Dj, = 4 and fori # j, Diy =
0. Finally, the number of Ay which are nonzero is the rank of the matrix, the
eigenvectors which correspond to the nonzero eigenvalues span the range of A,

and the eigenvectors which correspond to zero eigenvalues span the null space of

A.

Positive definite matrices

Asymmetric matrix A € R“* is positive definite if all its eigenvalues are positive.
A is positive semidefinite if all its eigenvalues are nonnegative.

THEOREM C.2. Let A € R* be a symmetric matrix. Then, the following are
equivalent definitions of positive semidefiniteness of A:

e All the eigenvalues of A are nonnegative.
e For every vector u, (u, Au) > 0.
e There exists a matrix B such that A= BB".

Singular Value Decomposition (SVD)

Let A € R™” be a matrix of rank r. When m ¥ n, the eigenvalue decomposition
given in Theorem C.1 cannot be applied. We will describe another decomposition
of A, which is called Singular Value Decomposition, or SVD for short.

Unit vectors v € R” and u € R™ are called right and left singular vectors of
A with corresponding singular value o > 0 if

Av=ou and Alu=ov.

We first show that if we can find r orthonormal singular vectors with positive
singular values, then we can decompose A = UDV', with the columns of U and
V containing the left and right singular vectors, and D being a diagonal r x r
matrix with the singular values on its diagonal.

432

Linear Algebra

LEMMA C.3 Let AG R™"” be a matrix of rank r. Assume that v1,...,V, is an
orthonormal set of right singular vectors of A, ui1,...,U, is an orthonormal set
of corresponding left singular vectors of A, and o1,...,0, are the corresponding

singular values. Then,
r
A= Ss ov) .
i=l

It follows that if U is a matrix whose columns are the u;’s, V is a matrix whose
columns are the v;’s, and D is a diagonal matrix with Dj; = 0;, then

A=UDV'".

Proof Any right singular vector of A must be in the range of A‘ (otherwise,
the singular value will have to be zero). Therefore, vi,...,V, is an orthonormal
basis of the range of A. Let us complete it to an orthonormal basis of R" by
adding the vectors v;+1,...,Vn- Define B = an ou; - It suffices to prove
that for all i, Av; = Bv;. Clearly, if i > r then Av; = 0 and Bv; = 0 as well.
For i < r we have
r
By, = Ss ojUjVj Vi = oj; = Avi,
j=l

where the last equality follows from the definition.

The next lemma relates the singular values of A to the eigenvalues of A’ A

and AAT.

LEMMA C.4_ v,u are right and left singular vectors of A with singular value o

iff v is an eigenvector of A' A with corresponding eigenvalue 0? and u = 071 Av

is an eigenvector of AA' with corresponding eigenvalue o?.

Proof Suppose that o is a singular value of A with v € R” being the corre-
sponding right singular vector. Then,
Al Av =cAlu=o’v.
Similarly,
AA'u=ocAv =07u.
For the other direction, if \ 4 0 is an eigenvalue of A'A, with v being the

corresponding eigenvector, then \ > 0 because A" A is positive semidefinite. Let

o =Vi,u=07'!Av. Then,
Av
Vx

ou=VA = Av,

and

1 r
Alu=—A' Av = “v=ov.
oO oO


C.4 Singular Value Decomposition (SVD) 433

Finally, we show that if A has rank r then it has r orthonormal singular
vectors.

LEMMA C.5 Let AE R™"” with rank r. Define the following vectors:

vi = argmax |jAv||
veR™:||v||=1

v2 = argmax |jAv||
veR™:||v||=1
(v,v1)=0

v,=  argmax _||Av||
VER": ||v||=1
vi<r, (v,vi)=0

Then, V1,...,; Vy is an orthonormal set of right singular vectors of A.

Proof First note that since the rank of A is r, the range of A is a subspace of
dimension r, and therefore it is easy to verify that for alli =1,...,r, ||Avi|| > 0.
Let W € R™” be an orthonormal matrix obtained by the eigenvalue decompo-
sition of A’ A, namely, A'A = WDW', with D being a diagonal matrix with
Di > Do. >--- > 0. We will show that vi,...,v, are eigenvectors of ATA
that correspond to nonzero eigenvalues, and, hence, using Lemma C.4 it follows
that these are also right singular vectors of A. The proof is by induction. For the
basis of the induction, note that any unit vector v can be written as v = Wx,
for x = W'v, and note that ||x|| = 1. Therefore,

n
|Av|? = | AWx|? = || WDW'Wx(? = ||WDx|?? = ||Dx\)? =) 0 Di 2?.
i=1

Therefore,
n
max ||Av||? = max D? xi?

iiti -
v:||v|J=1 x:||x||=1 ,
lvl Tell i=l

The solution of the right-hand side is to set x = (1,0,...,0), which implies that
v1 is the first eigenvector of A' A. Since ||Avj|| > 0 it follows that Dj, > 0 as
required. For the induction step, assume that the claim holds for some 1 < t <
r—1. Then, any v which is orthogonal to v;,...,v, can be written as v = Wx
with all the first t elements of x being zero. It follows that

[AIP = max > Din?.

max
vill v|=LVi<tvT vi= x: |[x||=1
i=t+1

The solution of the right-hand side is the all zeros vector except x141 = 1. This
implies that v,41 is the (¢ + 1)th column of W. Finally, since ||Avi+1|| > 0 it
follows that D141,441 > 0 as required. This concludes our proof.


434

Linear Algebra

COROLLARY C.6 (The SVD theorem) Let A € R™” with rank r. Then A =
UDV" where D is anr x r matrix with nonzero singular values of A and the
columns of U,V are orthonormal left and right singular vectors of A. Further-
more, for all i, D?, is an eigenvalue of A'A, the ith column of V is the cor-
responding eigenvector of A'A and the ith column of U is the corresponding
eigenvector of AA‘.

Notes

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning


References

Abernethy, J., Bartlett, P. L., Rakhlin, A. & Tewari, A. (2008), Optimal strategies and
minimax lower bounds for online convex games, in ‘Proceedings of the Nineteenth
Annual Conference on Computational Learning Theory’.

Ackerman, M. & Ben-David, S. (2008), Measures of clustering quality: A working set
of axioms for clustering, in ‘Proceedings of Neural Information Processing Systems
(NIPS)’, pp. 121-128.

Agarwal, S. & Roth, D. (2005), Learnability of bipartite ranking functions, in ‘Pro-
ceedings of the 18th Annual Conference on Learning Theory’, pp. 16-31.

Agmon, S. (1954), ‘The relaxation method for linear inequalities’, Canadian Journal
of Mathematics 6(3), 382-392.

Aizerman, M. A., Braverman, E. M. & Rozonoer, L. I. (1964), “Theoretical foundations
of the potential function method in pattern recognition learning’, Automation and
Remote Control 25, 821-837.

Allwein, E. L., Schapire, R. & Singer, Y. (2000), ‘Reducing multiclass to binary: A uni-
fying approach for margin classifiers’, Journal of Machine Learning Research 1, 113-
141.

Alon, N., Ben-David, S., Cesa-Bianchi, N. & Haussler, D. (1997), ‘Scale-sensitive dimen-
sions, uniform convergence, and learnability’, Journal of the ACM 44(4), 615-631.
Anthony, M. & Bartlet, P. (1999), Neural Network Learning: Theoretical Foundations,

Cambridge University Press.

Baraniuk, R., Davenport, M., DeVore, R. & Wakin, M. (2008), ‘A simple proof of
the restricted isometry property for random matrices’, Constructive Approximation
28(3), 253-263.

Barber, D. (2012), Bayesian reasoning and machine learning, Cambridge University
Press.

Bartlett, P., Bousquet, O. & Mendelson, S. (2005), ‘Local rademacher complexities’,
Annals of Statistics 33(4), 1497-1537.

Bartlett, P. L. & Ben-David, S. (2002), ‘Hardness results for neural network approxi-
mation problems’, Theor. Comput. Sci. 284(1), 53-66.

Bartlett, P. L., Long, P. M. & Williamson, R. C. (1994), Fat-shattering and the learn-
ability of real-valued functions, in ‘Proceedings of the seventh annual conference on
Computational learning theory’, ACM, pp. 299-310.

Bartlett, P. L. & Mendelson, S. (2001), Rademacher and Gaussian complexities: Risk
bounds and structural results, in ‘14th Annual Conference on Computational Learn-
ing Theory, COLT 2001’, Vol. 2111, Springer, Berlin, pp. 224-240.

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David
Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.

Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

438

References

Bartlett, P. L. & Mendelson, S. (2002), ‘Rademacher and Gaussian complexities: Risk
bounds and structural results’, Journal of Machine Learning Research 3, 463-482.
Ben-David, S., Cesa-Bianchi, N., Haussler, D. & Long, P. (1995), ‘Characterizations

of learnability for classes of {0,...,n}-valued functions’, Journal of Computer and
System Sciences 50, 74-86.
Ben-David, S., Eiron, N. & Long, P. (2003), ‘On the difficulty of approximately maxi-
mizing agreements’, Journal of Computer and System Sciences 66(3), 496-514.
Ben-David, S. & Litman, A. (1998), ‘Combinatorial variability of vapnik-chervonenkis
classes with applications to sample compression schemes’, Discrete Applied Mathe-
matics 86(1), 3-25.
Ben-David, S., Pal, D., & Shalev-Shwartz, S. (2009), Agnostic online learning, in ‘Con-
ference on Learning Theory (COLT)’.
Ben-David, S. & Simon, H. (2001), ‘Efficient learning of linear perceptrons’, Advances
in Neural Information Processing Systems pp. 189-195.

Bengio, Y. (2009), ‘Learning deep architectures for AI’, Foundations and Trends in
Machine Learning 2(1), 1-127.

Bengio, Y. & LeCun, Y. (2007), ‘Scaling learning algorithms towards ai’, Large-Scale
Kernel Machines 34.

Bertsekas, D. (1999), Nonlinear Programming, Athena Scientific.

Beygelzimer, A., Langford, J. & Ravikumar, P. (2007), ‘Multiclass classification with
filter trees’, Preprint, June .

Birkhoff, G. (1946), ‘Three observations on linear algebra’, Revi. Univ. Nac. Tucuman,
ser A 5, 147-151.

Bishop, C. M. (2006), Pattern recognition and machine learning, Vol. 1, springer New
York.

Blum, L., Shub, M. & Smale, S. (1989), ‘On a theory of computation and complexity
over the real numbers: Np-completeness, recursive functions and universal machines’,
Am. Math. Soc 21(1), 1-46.

Blumer, A., Ehrenfeucht, A., Haussler, D. & Warmuth, M. K. (1987), ‘Occam’s razor’,
Information Processing Letters 24(6), 377-380.

Blumer, A., Ehrenfeucht, A., Haussler, D. & Warmuth, M. K. (1989), ‘Learnability
and the Vapnik-Chervonenkis dimension’, Journal of the Association for Computing
Machinery 36(4), 929-965.

Borwein, J. & Lewis, A. (2006), Convex Analysis and Nonlinear Optimization, Springer.
Boser, B. E., Guyon, I. M. & Vapnik, V. N. (1992), A training algorithm for optimal
margin classifiers, in ‘Conference on Learning Theory (COLT)’, pp. 144-152.
Bottou, L. & Bousquet, O. (2008), The tradeoffs of large scale learning, in ‘NIPS’,
pp. 161-168.

Boucheron, S., Bousquet, O. & Lugosi, G. (2005), ‘Theory of classification: a survey of
recent advances’, ESAIM: Probability and Statistics 9, 323-375.

Bousquet, O. (2002), Concentration Inequalities and Empirical Processes Theory Ap-
plied to the Analysis of Learning Algorithms, PhD thesis, Ecole Polytechnique.
Bousquet, O. & Elisseeff, A. (2002), ‘Stability and generalization’, Journal of Machine
Learning Research 2, 499-526.

Boyd, S. & Vandenberghe, L. (2004), Conver Optimization, Cambridge University
Press.


References 439

Breiman, L. (1996), Bias, variance, and arcing classifiers, Technical Report 460, Statis-
tics Department, University of California at Berkeley.

Breiman, L. (2001), ‘Random forests’, Machine learning 45(1), 5-32.

Breiman, L., Friedman, J. H., Olshen, R. A. & Stone, C. J. (1984), Classification and
Regression Trees, Wadsworth & Brooks.

Candés, E. (2008), ‘The restricted isometry property and its implications for com-
pressed sensing’, Comptes Rendus Mathematique 346(9), 589-592.

Candes, E. J. (2006), Compressive sampling, in ‘Proc. of the Int. Congress of Math.,
Madrid, Spain’.

Candes, E. & Tao, T. (2005), ‘Decoding by linear programming’, [EEE Trans. on
Information Theory 51, 4203-4215.

Cesa-Bianchi, N. & Lugosi, G. (2006), Prediction, learning, and games, Cambridge
University Press.

Chang, H. S., Weiss, Y. & Freeman, W. T. (2009), ‘Informative sensing’, arXiv preprint
arXiv:0901.4275 .

Chapelle, O., Le, Q. & Smola, A. (2007), Large margin optimization of ranking mea-
sures, in ‘NIPS Workshop: Machine Learning for Web Search’.

Collins, M. (2000), Discriminative reranking for natural language parsing, in ‘Machine
Learning’.

Collins, M. (2002), Discriminative training methods for hidden Markov models: Theory
and experiments with perceptron algorithms, in ‘Conference on Empirical Methods
in Natural Language Processing’.

Collobert, R. & Weston, J. (2008), A unified architecture for natural language process-
ing: deep neural networks with multitask learning, in ‘International Conference on
Machine Learning (ICML)’.

Cortes, C. & Vapnik, V. (1995), ‘Support-vector networks’, Machine Learning
20(3), 273-297.

Cover, T. (1965), ‘Behavior of sequential predictors of binary sequences’, Trans. 4th
Prague Conf. Information Theory Statistical Decision Functions, Random Processes
pp. 263-272.

Cover, T. & Hart, P. (1967), ‘Nearest neighbor pattern classification’, Information
Theory, IEEE Transactions on 13(1), 21-27.

Crammer, K. & Singer, Y. (2001), ‘On the algorithmic implementation of multiclass
kernel-based vector machines’, Journal of Machine Learning Research 2, 265-292.
Cristianini, N. & Shawe-Taylor, J. (2000), An Introduction to Support Vector Machines,

Cambridge University Press.

Daniely, A., Sabato, S., Ben-David, S. & Shalev-Shwartz, S. (2011), Multiclass learn-
ability and the erm principle, in ‘Conference on Learning Theory (COLT)’.

Daniely, A., Sabato, S. & Shwartz, S. S. (2012), Multiclass learning approaches: A
theoretical comparison with implications, in ‘NIPS’.

Davis, G., Mallat, S. & Avellaneda, M. (1997), ‘Greedy adaptive approximation’, Jour-
nal of Constructive Approximation 13, 57-98.

Devroye, L. & Gyérfi, L. (1985), Nonparametric Density Estimation: The L B1 S View,
Wiley.

Devroye, L., Gyérfi, L. & Lugosi, G. (1996), A Probabilistic Theory of Pattern Recog-
nition, Springer.

440

References

Dietterich, T. G. & Bakiri, G. (1995), ‘Solving multiclass learning problems via error-
correcting output codes’, Journal of Artificial Intelligence Research 2, 263-286.
Donoho, D. L. (2006), ‘Compressed sensing’, Information Theory, IEEE Transactions
on 52(4), 1289-1306.

Dudley, R., Gine, E. & Zinn, J. (1991), ‘Uniform and universal glivenko-cantelli classes’,

Journal of Theoretical Probability 4(3), 485-510.

Dudley, R. M. (1987), ‘Universal Donsker classes and metric entropy’, Annals of Prob-

ability 15(4), 1306-1326.

Fisher, R. A. (1922), ‘On the mathematical foundations of theoretical statistics’, Philo-

sophical Transactions of the Royal Society of London. Series A, Containing Papers

of a Mathematical or Physical Character 222, 309-368.

Floyd, S. (1989), Space-bounded learning and the Vapnik-Chervonenkis dimension, in
‘Conference on Learning Theory (COLT)’, pp. 349-364.

Floyd, S. & Warmuth, M. (1995), ‘Sample compression, learnability, and the Vapnik-
Chervonenkis dimension’, Machine Learning 21(3), 269-304.

Frank, M. & Wolfe, P. (1956), ‘An algorithm for quadratic programming’, Naval Res.
Logist. Quart. 3, 95-110.

Freund, Y. & Schapire, R. (1995), A decision-theoretic generalization of on-line learning
and an application to boosting, in ‘European Conference on Computational Learning
Theory (EuroCOLT)’, Springer-Verlag, pp. 23-37.

Freund, Y. & Schapire, R. E. (1999), ‘Large margin classification using the perceptron
algorithm’, Machine Learning 37(3), 277-296.

Garcia, J. & Koelling, R. (1996), ‘Relation of cue to consequence in avoidance learning’,

Foundations of animal behavior: classic papers with commentaries 4, 374.

Gentile, C. (2003), ‘The robustness of the p-norm algorithms’, Machine Learning
53(3), 265-299.

Georghiades, A., Belhumeur, P. & Kriegman, D. (2001), ‘From few to many: Illumina-
tion cone models for face recognition under variable lighting and pose’, [EEE Trans.
Pattern Anal. Mach. Intelligence 23(6), 643-660.

Gordon, G. (1999), Regret bounds for prediction problems, in ‘Conference on Learning
Theory (COLT)’.

Gottlieb, L.-A., Kontorovich, L. & Krauthgamer, R. (2010), Efficient classification for
metric data, in ‘23rd Conference on Learning Theory’, pp. 433-440.

Guyon, I. & Elisseeff, A. (2003), ‘An introduction to variable and feature selection’,
Journal of Machine Learning Research, Special Issue on Variable and Feature Selec-
tion 3, 1157-1182.

Hadamard, J. (1902), ‘Sur les problémes aux dérivées partielles et leur signification
physique’, Princeton University Bulletin 13, 49-52.

Hastie, T., Tibshirani, R. & Friedman, J. (2001), The Elements of Statistical Learning,
Springer.

Haussler, D. (1992), ‘Decision theoretic generalizations of the PAC model for neural
net and other learning applications’, Information and Computation 100(1), 78-150.

Haussler, D. & Long, P. M. (1995), ‘A generalization of sauer’s lemma’, Journal of
Combinatorial Theory, Series A '71(2), 219-240.

Hazan, E., Agarwal, A. & Kale, S. (2007), ‘Logarithmic regret algorithms for online
convex optimization’, Machine Learning 69(2-3), 169-192.

References 441

Hinton, G. E., Osindero, S. & Teh, Y.-W. (2006), ‘A fast learning algorithm for deep
belief nets’, Neural Computation 18(7), 1527-1554.

Hiriart-Urruty, J.-B. & Lemaréchal, C. (1996), Convex Analysis and Minimization Al-
gorithms: Part 1: Fundamentals, Vol. 1, Springer.

Hsu, C.-W., Chang, C.-C. & Lin, C.-J. (2003), ‘A practical guide to support vector
classification’.

Hyafil, L. & Rivest, R. L. (1976), ‘Constructing optimal binary decision trees is NP-
complete’, Information Processing Letters 5(1), 15-17.

Joachims, T. (2005), A support vector method for multivariate performance measures,
in ‘Proceedings of the International Conference on Machine Learning (ICML)’.

Kakade, S., Sridharan, K. & Tewari, A. (2008), On the complexity of linear prediction:
Risk bounds, margin bounds, and regularization, in ‘NIPS’.

Karp, R. M. (1972), Reducibility among combinatorial problems, Springer.

Kearns, M. J., Schapire, R. E. & Sellie, L. M. (1994), ‘Toward efficient agnostic learn-
ing’, Machine Learning 17, 115-141.

Kearns, M. & Mansour, Y. (1996), On the boosting ability of top-down decision tree
learning algorithms, in ‘ACM Symposium on the Theory of Computing (STOC)’.
Kearns, M. & Ron, D. (1999), ‘Algorithmic stability and sanity-check bounds for leave-

one-out cross-validation’, Neural Computation 11(6), 1427-1453.

Kearns, M. & Valiant, L. G. (1988), Learning Boolean formulae or finite automata is
as hard as factoring, Technical Report TR-14-88, Harvard University Aiken Compu-
tation Laboratory.

Kearns, M. & Vazirani, U. (1994), An Introduction to Computational Learning Theory,
MIT Press.

Kleinberg, J. (2003), ‘An impossibility theorem for clustering’, Advances in Neural
Information Processing Systems pp. 463-470.

Klivans, A. R. & Sherstov, A. A. (2006), Cryptographic hardness for learning intersec-
tions of halfspaces, in ‘FOCS’.

Koller, D. & Friedman, N. (2009), Probabilistic Graphical Models: Principles and Tech-
niques, MIT Press.

Koltchinskii, V. & Panchenko, D. (2000), Rademacher processes and bounding the risk
of function learning, in ‘High Dimensional Probability II’, Springer, pp. 443-457.
Kuhn, H. W. (1955), ‘The hungarian method for the assignment problem’, Naval re-

search logistics quarterly 2(1-2), 83-97.

Kutin, S. & Niyogi, P. (2002), Almost-everywhere algorithmic stability and general-
ization error, in ‘Proceedings of the 18th Conference in Uncertainty in Artificial
Intelligence’, pp. 275-282.

Lafferty, J., McCallum, A. & Pereira, F. (2001), Conditional random fields: Probabilistic
models for segmenting and labeling sequence data, in ‘International Conference on
Machine Learning’, pp. 282-289.

Langford, J. (2006), ‘Tutorial on practical prediction theory for classification’, Journal
of machine learning research 6(1), 273.

Langford, J. & Shawe-Taylor, J. (2003), PAC-Bayes & margins, in ‘NIPS’, pp. 423-430.

Le Cun, L. (2004), Large scale online learning., in ‘Advances in Neural Information
Processing Systems 16: Proceedings of the 2003 Conference’, Vol. 16, MIT Press,
p. 217.

442

References

Le, Q. V., Ranzato, M.-A., Monga, R., Devin, M., Corrado, G., Chen, K., Dean, J. &
Ng, A. Y. (2012), Building high-level features using large scale unsupervised learning,
in ‘International Conference on Machine Learning (ICML)’.

Lecun, Y. & Bengio, Y. (1995), Convolutional Networks for Images, Speech and Time

Series, The MIT Press, pp. 255-258.

Lee, H., Grosse, R., Ranganath, R. & Ng, A. (2009), Convolutional deep belief networks

for scalable unsupervised learning of hierarchical representations, in ‘International

Conference on Machine Learning (ICML)’.

Littlestone, N. (1988), ‘Learning quickly when irrelevant attributes abound: A new

linear-threshold algorithm’, Machine Learning 2, 285-318.

Littlestone, N. & Warmuth, M. (1986), Relating data compression and learnability.

Unpublished manuscript.

Littlestone, N. & Warmuth, M. K. (1994), ‘The weighted majority algorithm’, Infor-

mation and Computation 108, 212-261.

Livni, R., Shalev-Shwartz, S. & Shamir, O. (2013), ‘A provably efficient algorithm for

training deep networks’, arXiv preprint arXiv:1304.7045 .

Livni, R. & Simon, P. (2013), Honest compressions and their application to compression

schemes, in ‘Conference on Learning Theory (COLT)’.

MacKay, D. J. (2003), Information theory, inference and learning algorithms,

Cambridge university press.

Mallat, S. & Zhang, Z. (1993), ‘Matching pursuits with time-frequency dictionaries’,

IEEE Transactions on Signal Processing 41, 3397-3415.

{cAllester, D. A. (1998), Some PAC-Bayesian theorems, in ‘Conference on Learning

Theory (COLT)’.

{cAllester, D. A. (1999), PAC-Bayesian model averaging, in ‘Conference on Learning

Theory (COLT)’, pp. 164-170.

AcAllester, D. A. (2003), Simplified PAC-Bayesian margin bounds., in ‘Conference on

Learning Theory (COLT)’, pp. 203-215.

Jinsky, M. & Papert, S. (1969), Perceptrons: An Introduction to Computational Ge-

ometry, The MIT Press.

Jukherjee, S., Niyogi, P., Poggio, T. & Rifkin, R. (2006), ‘Learning theory: stability is

sufficient for generalization and necessary and sufficient for consistency of empirical

risk minimization’, Advances in Computational Mathematics 25(1-3), 161-193.

Jurata, N. (1998), ‘A statistical study of on-line learning’, Online Learning and Neural

Networks. Cambridge University Press, Cambridge, UK .

Jurphy, K. P. (2012), Machine learning: a probabilistic perspective, The MIT Press.
atarajan, B. (1995), ‘Sparse approximate solutions to linear systems’, SIAM J. Com-
puting 25(2), 227-234.
atarajan, B. K. (1989), ‘On learning sets and functions’, Mach. Learn. 4, 67-97.
emirovski, A., Juditsky, A., Lan, G. & Shapiro, A. (2009), ‘Robust stochastic ap-
proximation approach to stochastic programming’, SJAM Journal on Optimization
19(4), 1574-1609.
emirovski, A. & Yudin, D. (1978), Problem complexity and method efficiency in opti-
mization, Nauka Publishers, Moscow.
esterov, Y. (2005), Primal-dual subgradient methods for convex problems, Technical
report, Center for Operations Research and Econometrics (CORE), Catholic Univer-
sity of Louvain (UCL).


References 443

Nesterov, Y. & Nesterov, I. (2004), Introductory lectures on convex optimization: A
basic course, Vol. 87, Springer Netherlands.

Novikoff, A. B. J. (1962), On convergence proofs on perceptrons, in ‘Proceedings of the
Symposium on the Mathematical Theory of Automata’, Vol. XII, pp. 615-622.

Parberry, I. (1994), Circuit complexity and neural networks, The MIT press.

Pearson, K. (1901), ‘On lines and planes of closest fit to systems of points in space’,
The London, Edinburgh, and Dublin Philosophical Magazine and Journal of Science
2(11), 559-572.

Phillips, D. L. (1962), ‘A technique for the numerical solution of certain integral equa-
tions of the first kind’, Journal of the ACM 9(1), 84-97.

Pisier, G. (1980-1981), ‘Remarques sur un résultat non publié de B. maurey’.

Pitt, L. & Valiant, L. (1988), ‘Computational limitations on learning from examples’,
Journal of the Association for Computing Machinery 35(4), 965-984.

Poon, H. & Domingos, P. (2011), Sum-product networks: A new deep architecture, in
‘Conference on Uncertainty in Artificial Intelligence (UAI)’.

Quinlan, J. R. (1986), ‘Induction of decision trees’, Machine Learning 1, 81-106.

Quinlan, J. R. (1993), C4.5: Programs for Machine Learning, Morgan Kaufmann.

Rabiner, L. & Juang, B. (1986), ‘An introduction to hidden markov models’, [EEE
ASSP Magazine 3(1), 4-16.

Rakhlin, A., Shamir, O. & Sridharan, K. (2012), Making gradient descent optimal for
strongly convex stochastic optimization, in ‘International Conference on Machine
Learning (ICML)’.

Rakhlin, A., Sridharan, K. & Tewari, A. (2010), Online learning: Random averages,
combinatorial parameters, and learnability, in ‘NIPS’.

Rakhlin, $., Mukherjee, S. & Poggio, T. (2005), ‘Stability results in learning theory’,
Analysis and Applications 3(4), 397-419.

Ranzato, M., Huang, F., Boureau, Y. & Lecun, Y. (2007), Unsupervised learning of
invariant feature hierarchies with applications to object recognition, in ‘Computer
Vision and Pattern Recognition, 2007. CVPR’07. IEEE Conference on’, IEEE, pp. 1—
8.

Rissanen, J. (1978), ‘Modeling by shortest data description’, Automatica 14, 465-471.

Rissanen, J. (1983), ‘A universal prior for integers and estimation by minimum descrip-
tion length’, The Annals of Statistics 11(2), 416-431.

Robbins, H. & Monro, S. (1951), ‘A stochastic approximation method’, The Annals of
Mathematical Statistics pp. 400-407.

Rogers, W. & Wagner, T. (1978), ‘A finite sample distribution-free performance bound
for local discrimination rules’, The Annals of Statistics 6(3), 506-514.

Rokach, L. (2007), Data mining with decision trees: theory and applications, Vol. 69,
World scientific.

Rosenblatt, F. (1958), ‘The perceptron: A probabilistic model for information storage
and organization in the brain’, Psychological Review 65, 386-407. (Reprinted in
Neurocomputing (MIT Press, 1988).).

Rumelhart, D. E., Hinton, G. E. & Williams, R. J. (1986), Learning internal represen-
tations by error propagation, in D. E. Rumelhart & J. L. McClelland, eds, ‘Paral-
lel Distributed Processing — Explorations in the Microstructure of Cognition’, MIT
Press, chapter 8, pp. 318-362.

444

References

Sankaran, J. K. (1993), ‘A note on resolving infeasibility in linear programs by con-
straint relaxation’, Operations Research Letters 13(1), 19-20.

Sauer, N. (1972), ‘On the density of families of sets’, Journal of Combinatorial Theory
Series A 13, 145-147.

Schapire, R. (1990), ‘The strength of weak learnability’, Machine Learning 5(2), 197—

227.

Schapire, R. E. & Freund, Y. (2012), Boosting: Foundations and Algorithms, MIT press.

Schélkopf, B., Herbrich, R. & Smola, A. (2001), A generalized representer theorem, in

‘Computational learning theory’, pp. 416-426.

Schélkopf, B., Herbrich, R., Smola, A. & Williamson, R. (2000), A generalized repre-

senter theorem, in ‘NeuroCOLT’.

Schélkopf, B. & Smola, A. J. (2002), Learning with Kernels: Support Vector Machines,

Regularization, Optimization and Beyond, MIT Press.

Schélkopf, B., Smola, A. & Miiller, K.-R. (1998), ‘Nonlinear component analysis as a

ernel eigenvalue problem’, Neural computation 10(5), 1299-1319.

Seeger, M. (2003), ‘Pac-bayesian generalisation error bounds for gaussian process clas-
sification’, The Journal of Machine Learning Research 3, 233-269.

Shakhnarovich, G., Darrell, T. & Indyk, P. (2006), Nearest-neighbor methods in learning

and vision: theory and practice, MIT Press.

Shalev-Shwartz, S. (2007), Online Learning: Theory, Algorithms, and Applications,

PhD thesis, The Hebrew University.

Shalev-Shwartz, S. (2011), ‘Online learning and online convex optimization’, Founda-

tions and Trends®) in Machine Learning 4(2), 107-194.

Shalev-Shwartz, S., Shamir, O., Srebro, N. & Sridharan, K. (2010), ‘Learnability,

stability and uniform convergence’, The Journal of Machine Learning Research

9999, 2635-2670.

Shalev-Shwartz, S., Shamir, O. & Sridharan, K. (2010), Learning kernel-based halfs-

paces with the zero-one loss, in ‘Conference on Learning Theory (COLT)’.

Shalev-Shwartz, S., Shamir, O., Sridharan, K. & Srebro, N. (2009), Stochastic convex

optimization, in ‘Conference on Learning Theory (COLT)’.

Shalev-Shwartz, S. & Singer, Y. (2008), On the equivalence of weak learnability and
linear separability: New relaxations and efficient boosting algorithms, in ‘Proceedings
of the Nineteenth Annual Conference on Computational Learning Theory’.
Shalev-Shwartz, S., Singer, Y. & Srebro, N. (2007), Pegasos: Primal Estimated sub-
GrAdient SOlver for SVM, in ‘International Conference on Machine Learning’,
pp. 807-814.

Shalev-Shwartz, S. & Srebro, N. (2008), SVM optimization: Inverse dependence on
training set size, in ‘International Conference on Machine Learning’, pp. 928-935.

Shalev-Shwartz, S., Zhang, T. & Srebro, N. (2010), ‘Trading accuracy for sparsity
in optimization problems with sparsity constraints’, Siam Journal on Optimization
20, 2807-2832.

Shamir, O. & Zhang, T. (2013), Stochastic gradient descent for non-smooth optimiza-
tion: Convergence results and optimal averaging schemes, in ‘International Confer-
ence on Machine Learning (ICML)’.

n

hapiro, A., Dentcheva, D. & Ruszczyiski, A. (2009), Lectures on stochastic program-
ming: modeling and theory, Vol. 9, Society for Industrial and Applied Mathematics.

References 445

Shelah, S. (1972), ‘A combinatorial problem; stability and order for models and theories
in infinitary languages’, Pac. J. Math 4, 247-261.

Sipser, M. (2006), Introduction to the Theory of Computation, Thomson Course Tech-
nology.

Slud, E. V. (1977), ‘Distribution inequalities for the binomial law’, The Annals of
Probability 5(3), 404-412.

Steinwart, I. & Christmann, A. (2008), Support vector machines, Springerverlag New
York.

Stone, C. (1977), ‘Consistent nonparametric regression’, The annals of statistics
5(4), 595-620.

Taskar, B., Guestrin, C. & Koller, D. (2003), Max-margin markov networks, in ‘NIPS’.

Tibshirani, R. (1996), ‘Regression shrinkage and selection via the lasso’, J. Royal.
Statist. Soc B. 58(1), 267-288.

Tikhonov, A. N. (1943), ‘On the stability of inverse problems’, Dolk. Akad. Nauk SSSR
39(5), 195-198.

Tishby, N., Pereira, F. & Bialek, W. (1999), The information bottleneck method, in
‘The 37’th Allerton Conference on Communication, Control, and Computing’.

Tsochantaridis, I., Hofmann, T., Joachims, T. & Altun, Y. (2004), Support vector
machine learning for interdependent and structured output spaces, in ‘Proceedings
of the Twenty-First International Conference on Machine Learning’.

Valiant, L. G. (1984), ‘A theory of the learnable’, Communications of the ACM
27(11), 1134-1142.

Vapnik, V. (1992), Principles of risk minimization for learning theory, in J. E. Moody,
S. J. Hanson & R. P. Lippmann, eds, ‘Advances in Neural Information Processing
Systems 4’, Morgan Kaufmann, pp. 831-838.

Vapnik, V. (1995), The Nature of Statistical Learning Theory, Springer.

Vapnik, V. N. (1982), Estimation of Dependences Based on Empirical Data, Springer-
Verlag.

Vapnik, V. N. (1998), Statistical Learning Theory, Wiley.

Vapnik, V. N. & Chervonenkis, A. Y. (1971), ‘On the uniform convergence of relative
frequencies of events to their probabilities’, Theory of Probability and its applications
XVI(2), 264-280.

Vapnik, V. N. & Chervonenkis, A. Y. (1974), Theory of pattern recognition, Nauka,
Moscow. (In Russian).

Von Luxburg, U. (2007), ‘A tutorial on spectral clustering’, Statistics and computing
17(4), 395-416.

von Neumann, J. (1928), ‘Zur theorie der gesellschaftsspiele (on the theory of parlor
games)’, Math. Ann. 100, 295—320.

Von Neumann, J. (1953), ‘A certain zero-sum two-person game equivalent to the opti-
mal assignment problem’, Contributions to the Theory of Games 2, 5-12.

Vovk, V. G. (1990), Aggregating strategies, in ‘Conference on Learning Theory
(COLT)’, pp. 371-383.

Warmuth, M., Glocer, K. & Vishwanathan, S. (2008), Entropy regularized lpboost, in
‘Algorithmic Learning Theory (ALT)’.

Warmuth, M., Liao, J. & Ratsch, G. (2006), Totally corrective boosting algorithms
that maximize the margin, in ‘Proceedings of the 23rd international conference on

Machine learning’.

446

References

Weston, J., Chapelle, O., Vapnik, V., Elisseeff, A. & Schélkopf, B. (2002), Kernel depen-
dency estimation, in ‘Advances in neural information processing systems’, pp. 873—
880.

Weston, J. & Watkins, C. (1999), Support vector machines for multi-class pattern
recognition, in ‘Proceedings of the Seventh European Symposium on Artificial Neural
Networks’.

Wolpert, D. H. & Macready, W. G. (1997), ‘No free lunch theorems for optimization’,
Evolutionary Computation, IEEE Transactions on 1(1), 67-82.

Zhang, T. (2004), Solving large scale linear prediction problems using stochastic gradi-
ent descent algorithms, in ‘Proceedings of the Twenty-First International Conference
on Machine Learning’.

Zhao, P. & Yu, B. (2006), ‘On model selection consistency of Lasso’, Journal of Machine
Learning Research 7, 2541-2567.

Zinkevich, M. (2003), Online convex programming and generalized infinitesimal gradi-
ent ascent, in ‘International Conference on Machine Learning’.

Index

3-term DNF, 107
F-score, 244
£, norm, 183, 332, 363, 386

accuracy, 38, 43

activation function, 269
AdaBoost, 130, 134, 362
all-pairs, 228, 404
approximation error, 61, 64
auto-encoders, 368

backpropagation, 278
backward elimination, 363
bag-of-words, 209

base hypothesis, 137

Bayes optimal, 46, 52, 260
Bayes rule, 354

Bayesian reasoning, 353
Bennet’s inequality, 426
Bernstein’s inequality, 426
bias, 37, 61, 64
bias-complexity tradeoff, 65
boolean conjunctions, 51, 79, 106
boosting, 130

boosting the confidence, 142
boundedness, 165

C4.5, 254
CART, 254
chaining, 389
Chebyshev’s inequality, 423
Chernoff bounds, 423
class-sensitive feature mapping, 230
classifier, 34
clustering, 307

spectral, 315
compressed sensing, 330
compression bounds, 410
compression scheme, 411
computational complexity, 100
confidence, 38, 43
consistency, 92
Consistent, 289
contraction lemma, 381
convex, 156

function, 157

set, 156

strongly convex, 174, 195
convex-Lipschitz-bounded learning, 166
convex-smooth-bounded learning, 166
covering numbers, 388
curse of dimensionality, 263

decision stumps, 132, 133
decision trees, 250
dendrogram, 309, 310
dictionary learning, 368
differential set, 188
dimensionality reduction, 323
discretization trick, 57
discriminative, 342
distribution free, 342
domain, 33
domain of examples, 48
doubly stochastic matrix, 242
duality, 211

strong duality, 211

weak duality, 211
Dudley classes, 81

efficient computable, 100
EM, 348
empirical error, 35
empirical risk, 35, 48
Empirical Risk Minimization, see ERM
entropy, 345
relative entropy, 345
epigraph, 157
ERM, 35
error decomposition, 64, 168
estimation error, 61, 64
Expectation-Maximization, see EM

face recognition, see Viola-Jones
feasible, 100

feature, 33

feature learning, 368

feature normalization, 365
feature selection, 357, 358
feature space, 215

feature transformations, 367
filters, 359

Understanding Machine Learning, © 2014 by Shai Shalev-Shwartz and Shai Ben-David

Published 2014 by Cambridge University Press.

Personal use only. Not for distribution. Do not post.
Please link to http://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning

448

Index

forward greedy selection, 360
frequentist, 353

gain, 253

GD, see gradient descent
generalization error, 35
generative models, 342
Gini index, 254
Glivenko-Cantelli, 58
gradient, 158

gradient descent, 185
Gram matrix, 219
growth function, 73

halfspace, 118
homogenous, 118, 205
non-separable, 119
separable, 118

Halving, 289

hidden layers, 270

Hilbert space, 217

Hoeffding’s inequality, 56, 425

hold out, 146

hypothesis, 34

hypothesis class, 36

iid., 38

ID3, 252

improper, see representation independent

inductive bias, see bias
information bottleneck, 317
information gain, 254
instance, 33

instance space, 33
integral image, 143
Johnson-Lindenstrauss lemma, 329

k-means, 311, 313

soft k-means, 352
k-median, 312
k-medoids, 312
Kendall tau, 239
kernel PCA, 326
kernels, 215

Gaussian kernel, 220

kernel trick, 217

polynomial kernel, 220

RBF kernel, 220

label, 33

Lasso, 365, 386
generalization bounds, 386

latent variables, 348

LDA, 347

Ldim, 290, 291

learning curves, 153

least squares, 124

likelihood ratio, 348

linear discriminant analysis, see LDA

linear predictor, 117

homogenous, 118
linear programming, 119
linear regression, 122
linkage, 310
Lipschitzness, 160, 176, 191
sub-gradient, 190
Littlestone dimension, see Ldim
local minimum, 158
logistic regression, 126
loss, 35
loss function, 48
0-1 loss, 48, 167
absolute value loss, 124, 128, 166
convex loss, 163
generalized hinge-loss, 233
hinge loss, 167
Lipschitz loss, 166
log-loss, 345
logistic loss, 127
ramp loss, 209
smooth loss, 166
square loss, 48
surrogate loss, 167, 302

margin, 203

Markov’s inequality, 422

Massart lemma, 380

max linkage, 310

maximum a-posteriori, 355

maximum likelihood, 343

McDiarmid’s inequality, 378

MDL, 89, 90, 251

measure concentration, 55, 422

Minimum Description Length, see MDL

mistake bound, 288

mixture of Gaussians, 348

model selection, 144, 147

multiclass, 47, 227, 402
cost-sensitive, 232
linear predictors, 230, 405
multi-vector, 231, 406
Perceptron, 248
reductions, 227, 405
SGD, 235
SVM, 234

multivariate performance measures, 243

Naive Bayes, 347

Natarajan dimension, 402

NDCG, 239

Nearest Neighbor, 258
k-NN, 258

neural networks, 268
feedforward networks, 269
layered networks, 269
SGD, 277

no-free-lunch, 61

non-uniform learning, 84

Normalized Discounted Cumulative Gain,
see NDCG

Occam’s razor, 91
OMP, 360
one-vs-all, 227
one-vs-rest, see one-vs-all
one-vs.-all, 404
online convex optimization, 300
online gradient descent, 300
online learning, 287
optimization error, 168
oracle inequality, 179
orthogonal matching pursuit, see OMP
overfitting, 35, 65, 152
PAC, 43
agnostic PAC, 45, 46
agnostic PAC for general loss, 49
PAC-Bayes, 415
parametric density estimation, 342
PCA, 324
Pearson’s correlation coefficient, 359
Perceptron, 120
kernelized Perceptron, 225
multiclass, 248
online, 301
permutation matrix, 242
polynomial regression, 125
precision, 244
predictor, 34
prefix free language, 89
Principal Component Analysis, see PCA
prior knowledge, 63
Probably Approximately Correct, see PAC
projection, 193
projection lemma, 193
proper, 49
pruning, 254
Rademacher complexity, 375
random forests, 255
random projections, 329
ranking, 238
bipartite, 243
realizability, 37
recall, 244
regression, 47, 122, 172
regularization, 171
Tikhonov, 172, 174
regularized loss minimization, see RLM
representation independent, 49, 107
representative sample, 54, 375
representer theorem, 218
ridge regression, 172
kernel ridge regression, 225
RIP, 331
risk, 35, 45, 48
RLM, 171, 199

Index

sample complexity, 44
Sauer’s lemma, 73
self-boundedness, 162
sensitivity, 244
SGD, 190
shattering, 69, 403
single linkage, 310
Singular Value Decomposition, see SVD
Slud’s inequality, 428
smoothness, 162, 177, 198
SOA, 292
sparsity-inducing norms, 363
specificity, 244
spectral clustering, 315
SRM, 85, 145
stability, 173
Stochastic Gradient Descent, see SGD
strong learning, 132
Structural Risk Minimization, see SRM
structured output prediction, 236
sub-gradient, 188
Support Vector Machines, see SVM
SVD, 431
SVM, 202, 383
duality, 211
generalization bounds, 208, 383
hard-SVM, 203, 204
homogenous, 205
kernel trick, 217
soft-SVM, 206
support vectors, 210

target set, 47
term-frequency, 231
TF-IDF, 231

training error, 35

training set, 33

true error, 35, 45
underfitting, 65, 152
uniform convergence, 54, 55
union bound, 39
unsupervised learning, 308

validation, 144, 146
cross validation, 149
train-validation-test split, 150.
Vapnik-Chervonenkis dimension, see VC
dimension
VC dimension, 67, 70
version space, 289
Viola-Jones, 139

weak learning, 130, 131
Weighted-Majority, 295

449


