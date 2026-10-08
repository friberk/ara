/** Test data: page 7 of "Attention Is All You Need" and a claim that cites it. */

// Page 7 of "Attention Is All You Need" as PyMuPDF extracts it: the stored chunk runs from the attention
// discussion through §5 Training, which is why marking all of it covered nearly the whole page.
export const page7 = `A single convolutional layer with kernel width k < n does not connect all pairs of input and output
positions. Doing so requires a stack of O(n/k) convolutional layers in the case of contiguous kernels,
or O(logk(n)) in the case of dilated convolutions [18], increasing the length of the longest paths
between any two positions in the network. Convolutional layers are generally more expensive than
recurrent layers, by a factor of k. Even with k = n, however, the complexity of a separable
convolution is equal to the combination of a self-attention layer and a point-wise feed-forward layer,
the approach we take in our model.

As side benefit, self-attention could yield more interpretable models. We inspect attention distributions
from our models and present and discuss examples in the appendix. Not only do individual attention
heads clearly learn to perform different tasks, many appear to exhibit behavior related to the syntactic
and semantic structure of the sentences.


5  Training

This section describes the training regime for our models.


5.1  Training Data and Batching

We trained on the standard WMT 2014 English-German dataset consisting of about 4.5 million
sentence pairs. Sentences were encoded using byte-pair encoding [3], which has a shared source-
target vocabulary of about 37000 tokens. Sentence pairs were batched together by approximate sequence length.


5.2  Hardware and Schedule

We trained our models on one machine with 8 NVIDIA P100 GPUs. For our base models using
the hyperparameters described throughout the paper, each training step took about 0.4 seconds.`
export const headsClaim = 'It also examines the model’s learned attention patterns and reports that different attention heads appear to capture distinct syntactic and semantic behaviors.'
export const interpretability = [
  'As side benefit, self-attention could yield more interpretable models.',
  'We inspect attention distributions from our models and present and discuss examples in the appendix.',
  'Not only do individual attention heads clearly learn to perform different tasks, many appear to exhibit behavior related to the syntactic and semantic structure of the sentences.',
]
