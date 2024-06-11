# Vendor external deps for a simple c++ binary

The `vendor_src` dir is generated via

```
bazel vendor --vendor_dir=vendor_src //:bin
```

bazel binary is built at [96b90baf08172bb55844c2366111a0c39b6f9e14](https://github.com/bazelbuild/bazel/commits/master?author=meteorcloudy)

The vendor_dir contains:
```
$ tree -L 1 vendor_src
vendor_src
├── @bazel_features~.marker
├── @bazel_skylib~.marker
├── @platforms.marker
├── @platforms~host_platform~host_platform.marker
├── @rules_cc~.marker
├── @rules_java~.marker
├── @rules_python~.marker
├── VENDOR.bazel
├── _registries
├── bazel_features~
├── bazel_skylib~
├── platforms
├── platforms~host_platform~host_platform
├── rules_cc~
├── rules_java~
└── rules_python~
```

It's suprising building a simple C++ binary would require rules_java and rules_python.
