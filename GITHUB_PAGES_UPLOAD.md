# GitHub Pages 上传说明

本发布包已经按 `https://你的GitHub用户名.github.io/` 根路径构建。

## 上传步骤

1. 登录 GitHub，创建一个 **Public** 仓库。
2. 仓库名必须严格填写为 `你的GitHub用户名.github.io`。
3. 解压 `sol-100-motion-archive-github-pages.zip`。
4. 把解压后最外层的全部文件上传到仓库 `main` 分支根目录。不要只上传 ZIP，也不要再套一层文件夹。
5. 打开仓库的 `Settings` → `Pages`。
6. 在 `Build and deployment` 中选择 `Deploy from a branch`。
7. Branch 选择 `main`，文件夹选择 `/(root)`，点击 `Save`。
8. 等待 GitHub 完成发布后，打开 `https://你的GitHub用户名.github.io/`。

## 上传前确认

仓库最外层应直接看到：

```text
index.html
assets/
.nojekyll
404.html
catalog/
thanks/
exhibit/
favicon.svg
```

其中 `exhibit/` 内包含 `001` 至 `100`，用于保证每个展品地址刷新后仍能打开。
