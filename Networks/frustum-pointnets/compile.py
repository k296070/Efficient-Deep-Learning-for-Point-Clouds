import os

print("compiling: tf_interpolate_compile")
os.system('cd ./models_baseline/tf_ops/3d_interpolation; sh tf_interpolate_compile.sh')
os.system('cd ./models_limited/tf_ops/3d_interpolation; sh tf_interpolate_compile.sh')
os.system('cd ./models/tf_ops/3d_interpolation; sh tf_interpolate_compile.sh')
print("done")

print("compiling: tf_grouping_compile")
os.system('cd ./models_baseline/tf_ops/grouping; sh tf_grouping_compile.sh')
os.system('cd ./models_limited/tf_ops/3d_interpolation; sh tf_interpolate_compile.sh')
os.system('cd ./models/tf_ops/grouping; sh tf_grouping_compile.sh')
print("done")

print("compiling: tf_sampling_compile")
os.system('cd ./models_baseline/tf_ops/sampling/; sh tf_sampling_compile.sh')
os.system('cd ./models_limited/tf_ops/3d_interpolation; sh tf_interpolate_compile.sh')
os.system('cd ./models/tf_ops/sampling/; sh tf_sampling_compile.sh')
print("done")

