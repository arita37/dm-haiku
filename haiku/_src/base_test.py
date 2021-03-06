# Lint as: python3
# Copyright 2019 DeepMind Technologies Limited. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for haiku._src.base."""

import itertools as it

from absl.testing import absltest
from absl.testing import parameterized
from haiku._src import base
from haiku._src import test_utils
import jax
import jax.numpy as jnp
import numpy as np

# TODO(tomhennigan) Improve test coverage.


class BaseTest(parameterized.TestCase):

  @test_utils.transform_and_run
  def test_parameter_reuse(self):
    w1 = base.get_parameter("w", [], init=jnp.zeros)
    w2 = base.get_parameter("w", [], init=jnp.zeros)
    self.assertIs(w1, w2)

  def test_params(self):
    with base.new_context() as ctx:
      w = base.get_parameter("w", [], init=jnp.zeros)
    self.assertEqual(ctx.collect_params(), {"~": {"w": w}})

  @test_utils.transform_and_run
  def test_naked_get_parameter(self):
    w1 = base.get_parameter("w", [], init=jnp.zeros)
    w2 = base.get_parameter("w", [], init=jnp.zeros)
    self.assertIs(w1, w2)

  def test_naked_parameter_in_tilde_collection(self):
    with base.new_context() as ctx:
      w1 = base.get_parameter("w1", [], init=jnp.zeros)
      w2 = base.get_parameter("w2", [], init=jnp.ones)
      self.assertIsNot(w1, w2)
    self.assertEqual(ctx.collect_params(), {"~": {"w1": w1, "w2": w2}})

  @parameterized.parameters(({},), ({"~": {}},))
  def test_parameter_in_immutable_ctx(self, params):
    with base.new_context(params=params):
      with self.assertRaisesRegex(
          ValueError, "parameters must be created as part of `init`"):
        base.get_parameter("w", [], init=jnp.zeros)

  def test_get_parameter_wrong_shape(self):
    with base.new_context():
      with self.assertRaisesRegex(AssertionError, "does not match shape"):
        base.get_parameter("w", (1,), init=jnp.zeros)
        base.get_parameter("w", (2,), init=jnp.zeros)

  @parameterized.parameters(base.next_rng_key, lambda: base.next_rng_keys(1))
  def test_rng_no_transform(self, f):
    with self.assertRaisesRegex(ValueError,
                                "must be used as part of an `hk.transform`"):
      f()

  @test_utils.transform_and_run
  def test_rng(self):
    a = base.next_rng_key()
    b = base.next_rng_key()
    self.assertIsNot(a, b)

  @test_utils.transform_and_run
  def test_rngs(self):
    a, b = base.next_rng_keys(2)
    c, d = base.next_rng_keys(2)
    for l, r in it.permutations((a, b, c, d), 2):
      self.assertIsNot(l, r)

  @test_utils.transform_and_run(seed=None)
  def test_no_rng(self):
    with self.assertRaisesRegex(ValueError, "must pass a non-None PRNGKey"):
      base.next_rng_key()

  def test_invalid_rng(self):
    with self.assertRaisesRegex(ValueError, "not a JAX PRNGKey"):
      base.new_context(rng="nonsense")

  def test_invalid_rng_none_ignored(self):
    with base.new_context(rng=None):
      pass

  def test_maybe_rng_no_transform(self):
    with self.assertRaisesRegex(ValueError,
                                "must be used as part of an `hk.transform`"):
      base.maybe_next_rng_key()

  @test_utils.transform_and_run(seed=None)
  def test_maybe_no_rng(self):
    self.assertIsNone(base.maybe_next_rng_key())

  def test_maybe_rng_vs_not(self):
    """If we have an rng, then next_rng_key() == maybe_next_rng_key()."""
    rngs = []
    maybes = []

    @test_utils.transform_and_run
    def three():
      for _ in range(3):
        rngs.append(base.next_rng_key())

    @test_utils.transform_and_run
    def maybe_three():
      for _ in range(3):
        maybes.append(base.maybe_next_rng_key())

    three()
    maybe_three()
    self.assertLen(rngs, 6)
    self.assertTrue(jnp.all(jnp.array(rngs) == jnp.array(maybes)))

  def test_init_custom_creator(self):
    def zeros_creator(next_creator, shape, dtype, init, context):
      self.assertEqual(context.full_name, "~/w")
      self.assertEqual(shape, [])
      self.assertEqual(dtype, jnp.float32)
      self.assertEqual(init, jnp.ones)
      return next_creator(shape, dtype, jnp.zeros)

    with base.new_context() as ctx:
      with base.custom_creator(zeros_creator):
        base.get_parameter("w", [], init=jnp.ones)

    self.assertEqual(ctx.collect_params(), {"~": {"w": jnp.zeros([])}})

  def test_nested_creators(self):
    log = []

    def logging_creator(log_msg):
      def _logging_creator(next_creator, shape, dtype, init, context):
        del context
        log.append(log_msg)
        return next_creator(shape, dtype, init)
      return _logging_creator

    with base.new_context():
      with base.custom_creator(logging_creator("a")), \
           base.custom_creator(logging_creator("b")), \
           base.custom_creator(logging_creator("c")):
        base.get_parameter("w", [], init=jnp.ones)

    self.assertEqual(log, ["a", "b", "c"])

  def test_custom_getter_bf16(self):
    def bf16_getter(next_getter, value, context):
      del context
      if value.dtype == jnp.float32:
        value = value.astype(jnp.bfloat16)
      return next_getter(value)

    with base.new_context() as ctx:
      with base.custom_getter(bf16_getter):
        f = base.get_parameter("f", [], jnp.float32, init=jnp.ones)
        i = base.get_parameter("i", [], jnp.int32, init=jnp.ones)

    params = ctx.collect_params()
    self.assertEqual(params["~"]["f"].dtype, jnp.float32)
    self.assertEqual(f.dtype, jnp.bfloat16)
    self.assertEqual(params["~"]["i"].dtype, jnp.int32)
    self.assertEqual(i.dtype, jnp.int32)

  def test_nested_getters(self):
    log = []

    def logging_getter(log_msg, dtype_in, dtype_out):
      def _logging_getter(next_getter, value, context):
        del context
        log.append(log_msg)
        self.assertEqual(value.dtype, dtype_in)
        value = value.astype(dtype_out)
        return next_getter(value)
      return _logging_getter

    with base.new_context():
      with base.custom_getter(logging_getter("a", jnp.float32, jnp.bfloat16)), \
           base.custom_getter(logging_getter("b", jnp.bfloat16, jnp.int32)), \
           base.custom_getter(logging_getter("c", jnp.int32, jnp.int8)):
        w = base.get_parameter("w", [], init=jnp.ones)

    self.assertEqual(w.dtype, jnp.int8)
    self.assertEqual(log, ["a", "b", "c"])

  def test_creator_requires_context(self):
    def my_creator(next_creator, shape, dtype, init, context):
      del context
      return next_creator(shape, dtype, init)

    with self.assertRaisesRegex(ValueError,
                                "must be used as part of an `hk.transform`"):
      with base.custom_creator(my_creator):
        pass

  def test_getter_requires_context(self):
    def my_getter(next_getter, value, context):
      del context
      return next_getter(value)

    with self.assertRaisesRegex(ValueError,
                                "must be used as part of an `hk.transform`"):
      with base.custom_getter(my_getter):
        pass

  def test_get_state_no_init_raises(self):
    with base.new_context():
      with self.assertRaisesRegex(ValueError, "set an init function"):
        base.get_state("i")

    with base.new_context(state={"~": {}}):
      with self.assertRaisesRegex(ValueError, "set an init function"):
        base.get_state("i")

  def test_get_state_no_shape_raises(self):
    with base.new_context():
      with self.assertRaisesRegex(ValueError, "provide shape and dtype"):
        base.get_state("i", init=jnp.zeros)

    with base.new_context(state={"~": {}}):
      with self.assertRaisesRegex(ValueError, "provide shape and dtype"):
        base.get_state("i", init=jnp.zeros)

  def test_set_then_get(self):
    with base.new_context() as ctx:
      base.set_state("i", 1)
      base.get_state("i")

    self.assertEqual(ctx.collect_initial_state(), {"~": {"i": 1}})

    for _ in range(10):
      with ctx:
        base.set_state("i", 1)
        y = base.get_state("i")
        self.assertEqual(y, 1)
      self.assertEqual(ctx.collect_initial_state(), {"~": {"i": 1}})

  def test_stateful(self):
    with base.new_context() as ctx:
      for _ in range(10):
        count = base.get_state("count", (), jnp.int32, jnp.zeros)
        base.set_state("count", count + 1)

    self.assertEqual(ctx.collect_initial_state(), {"~": {"count": 0}})
    self.assertEqual(ctx.collect_state(), {"~": {"count": 10}})

  @parameterized.parameters((42, True), (42, False),
                            (28, True), (28, False))
  def test_prng_sequence(self, seed, wrap_seed):
    # Values using our sequence.
    key_or_seed = jax.random.PRNGKey(seed) if wrap_seed else seed
    key_seq = base.PRNGSequence(key_or_seed)
    seq_v1 = jax.random.normal(next(key_seq), [])
    seq_v2 = jax.random.normal(next(key_seq), [])
    # Generate values using manual splitting.
    key = jax.random.PRNGKey(seed)
    key, temp_key = jax.random.split(key)
    raw_v1 = jax.random.normal(temp_key, [])
    _, temp_key = jax.random.split(key)
    raw_v2 = jax.random.normal(temp_key, [])
    self.assertEqual(raw_v1, seq_v1)
    self.assertEqual(raw_v2, seq_v2)

  def test_prng_sequence_invalid_input(self):
    with self.assertRaisesRegex(ValueError, "not a JAX PRNGKey"):
      base.PRNGSequence("nonsense")

  def test_prng_sequence_wrong_shape(self):
    with self.assertRaisesRegex(ValueError,
                                "key did not have expected shape and/or dtype"):
      base.PRNGSequence(jax.random.split(jax.random.PRNGKey(42), 2))

  def test_prng_reserve(self):
    k = jax.random.PRNGKey(42)
    s = base.PRNGSequence(k)
    s.reserve(10)
    hk_keys = tuple(next(s) for _ in range(10))
    jax_keys = tuple(jax.random.split(k, num=11)[1:])
    jax.tree_multimap(np.testing.assert_equal, hk_keys, jax_keys)

  def test_prng_reserve_twice(self):
    k = jax.random.PRNGKey(42)
    s = base.PRNGSequence(k)
    s.reserve(2)
    s.reserve(2)
    hk_keys = tuple(next(s) for _ in range(4))
    k, subkey1, subkey2 = tuple(jax.random.split(k, num=3))
    _, subkey3, subkey4 = tuple(jax.random.split(k, num=3))
    jax_keys = (subkey1, subkey2, subkey3, subkey4)
    jax.tree_multimap(np.testing.assert_equal, hk_keys, jax_keys)

  def test_prng_sequence_split(self):
    k = jax.random.PRNGKey(42)
    s = base.PRNGSequence(k)
    hk_keys = s.take(10)
    jax_keys = tuple(jax.random.split(k, num=11)[1:])
    jax.tree_multimap(np.testing.assert_equal, hk_keys, jax_keys)

  @parameterized.parameters(42, 28)
  def test_with_rng(self, seed):
    ctx_key = jax.random.PRNGKey(seed * 2 + 1)
    key = jax.random.PRNGKey(seed)
    _, next_key = jax.random.split(key)
    expected_output = jax.random.uniform(next_key, ())

    with base.new_context(rng=ctx_key):
      without_decorator_out = jax.random.uniform(base.next_rng_key(), ()).item()

    with base.new_context(rng=ctx_key):
      with base.with_rng(key):
        with_decorator_out = jax.random.uniform(base.next_rng_key(), ()).item()

    self.assertNotEqual(without_decorator_out, expected_output)
    self.assertEqual(with_decorator_out, expected_output)

  def test_with_rng_no_transform(self):
    with self.assertRaisesRegex(ValueError,
                                "must be used as part of an `hk.transform`"):
      with base.with_rng(jax.random.PRNGKey(428)):
        pass

  def test_new_context(self):
    with base.new_context() as ctx:
      pass
    self.assertEmpty(ctx.collect_params())
    self.assertEmpty(ctx.collect_initial_state())
    self.assertEmpty(ctx.collect_state())

  def test_context_copies_input(self):
    before = {"~": {"w": jnp.array(1.)}}
    with base.new_context(params=before, state=before) as ctx:
      base.get_parameter("w", [], init=jnp.ones)
      base.set_state("w", jnp.array(2.))
    self.assertEqual(ctx.collect_params(), {"~": {"w": jnp.array(1.)}})
    self.assertIsNot(ctx.collect_initial_state(), before)
    self.assertEqual(ctx.collect_initial_state(), before)
    self.assertEqual(ctx.collect_state(), {"~": {"w": jnp.array(2.)}})
    self.assertEqual(before, {"~": {"w": jnp.array(1.)}})

  def test_assert_no_new_parameters(self):
    with base.new_context():
      base.get_parameter("w", [], init=jnp.zeros)
      with base.assert_no_new_parameters():
        # Should not raise, "w" already exists.
        base.get_parameter("w", [], init=jnp.zeros)

      with self.assertRaisesRegex(AssertionError,
                                  "New parameters were created: .*x"):
        with base.assert_no_new_parameters():
          # Should raise, "x" does not exist.
          base.get_parameter("x", [], init=jnp.zeros)

if __name__ == "__main__":
  absltest.main()
